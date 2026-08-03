#!/bin/bash
# Ralph Wiggum - Manager/OpenSpec agent loop
# Usage: ./ralph.sh [claude|codex|opencode] [max_iterations]
#        ./ralph.sh [--tool claude|codex|opencode] [max_iterations]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AGENT_FILE="$SCRIPT_DIR/AGENT.md"
PROGRESS_FILE="$SCRIPT_DIR/progress.txt"
LOG_DIR="$SCRIPT_DIR/logs"
FAILURE_LOG_DIR="$LOG_DIR/failures"
SUPPORTED_TOOLS="claude codex opencode"
COMPLETE_SIGNAL="<promise>COMPLETE</promise>"
RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"
STATE_FILE="$LOG_DIR/latest-state.md"
RALPH_AGENT_TIMEOUT="${RALPH_AGENT_TIMEOUT:-45m}"
RALPH_HEARTBEAT_SECONDS="${RALPH_HEARTBEAT_SECONDS:-30}"
RALPH_FAILURE_TAIL_LINES="${RALPH_FAILURE_TAIL_LINES:-40}"
RALPH_LAST_MESSAGE_LINES="${RALPH_LAST_MESSAGE_LINES:-80}"
RALPH_TRANSCRIPT_MAX_LINES="${RALPH_TRANSCRIPT_MAX_LINES:-100000}"
RALPH_TRANSCRIPT_KEEP_LINES="${RALPH_TRANSCRIPT_KEEP_LINES:-20000}"
HEARTBEAT_PID=""
CURRENT_ITERATION=""
CURRENT_TRANSCRIPT_FILE=""
CURRENT_LAST_MESSAGE_FILE=""
CURRENT_LOG_TIMESTAMP=""
CURRENT_STARTED_AT_EPOCH=""
TIMEOUT_AVAILABLE=0

print_usage() {
  cat <<EOF
Usage:
  ./scripts/ralph/ralph.sh [claude|codex|opencode] [max_iterations]
  ./scripts/ralph/ralph.sh --tool [claude|codex|opencode] [max_iterations]

Examples:
  bash ./scripts/ralph/ralph.sh codex 1
  bash ./scripts/ralph/ralph.sh claude 5
  bash ./scripts/ralph/ralph.sh opencode 5

Environment:
  RALPH_AGENT_TIMEOUT=45m       Agent command timeout; set 0/off/none to disable
  RALPH_HEARTBEAT_SECONDS=30    Progress heartbeat interval; set 0 to disable
  RALPH_LAST_MESSAGE_LINES=80   Tail lines kept in latest.last.txt for tools without structured final output
  RALPH_TRANSCRIPT_MAX_LINES=100000
                                Trim latest-transcript.log when it exceeds this many lines
  RALPH_TRANSCRIPT_KEEP_LINES=20000
                                Keep this many newest transcript lines after trimming
  RALPH_VERBOSE=1               Stream the full agent transcript
EOF
}

is_supported_tool() {
  [[ " $SUPPORTED_TOOLS " == *" $1 "* ]]
}

is_timeout_enabled() {
  [[ -n "$RALPH_AGENT_TIMEOUT" &&
    "$RALPH_AGENT_TIMEOUT" != "0" &&
    "$RALPH_AGENT_TIMEOUT" != "off" &&
    "$RALPH_AGENT_TIMEOUT" != "none" ]]
}

timeout_label() {
  if ! is_timeout_enabled; then
    echo "disabled"
  elif [ "$TIMEOUT_AVAILABLE" = "1" ]; then
    echo "$RALPH_AGENT_TIMEOUT"
  else
    echo "disabled (timeout command unavailable; requested $RALPH_AGENT_TIMEOUT)"
  fi
}

manager_current_field() {
  local key="$1"
  local plan_file="$PROJECT_ROOT/manager/plan.yaml"

  if [ ! -f "$plan_file" ]; then
    return 0
  fi

  awk -v key="$key" '
    /^current:/ { in_current = 1; next }
    /^[^[:space:]]/ { if (in_current) exit }
    in_current {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      if (line ~ "^" key ":[[:space:]]*") {
        sub("^" key ":[[:space:]]*", "", line)
        print line
        exit
      }
    }
  ' "$plan_file" 2>/dev/null || true
}

write_state() {
  local status="$1"
  local reason="${2:-}"
  local exit_status="${3:-}"

  mkdir -p "$LOG_DIR"
  {
    echo "# Ralph Run State"
    echo "- Updated: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "- Run id: $RUN_ID"
    echo "- Status: $status"
    [ -n "$reason" ] && echo "- Reason: $reason"
    [ -n "$exit_status" ] && echo "- Exit status: $exit_status"
    echo "- Tool: $TOOL"
    echo "- Max iterations: $MAX_ITERATIONS"
    echo "- Current iteration: ${CURRENT_ITERATION:-none}"
    echo "- Transcript: ${CURRENT_TRANSCRIPT_FILE:-none}"
    echo "- Last message: ${CURRENT_LAST_MESSAGE_FILE:-none}"
    echo "- Timeout: $(timeout_label)"
    echo "- Heartbeat seconds: $RALPH_HEARTBEAT_SECONDS"
    echo "- Manager current.title: $(manager_current_field title)"
    echo "- Manager current.batch: $(manager_current_field batch)"
    echo "- Manager current.wave: $(manager_current_field wave)"
    echo "- Manager current.next: $(manager_current_field next)"
    echo ""
    echo "## Recovery"
    echo "- Ralph does not roll back workspace edits or manager state automatically."
    echo "- To continue, inspect the transcript and rerun the Ralph command; the next iteration resumes from manager/plan.yaml and current files."
    echo "- If the partial state is unsafe, fix or mark the affected OpenSpec as blocked before rerunning."
  } > "$STATE_FILE"
}

append_progress_event() {
  local status="$1"
  local reason="$2"
  local exit_status="${3:-}"

  {
    echo "## [$(date '+%Y-%m-%d %H:%M:%S %Z')] - Ralph $status"
    echo "- Iteration: ${CURRENT_ITERATION:-none}/$MAX_ITERATIONS"
    echo "- Tool: $TOOL"
    [ -n "$exit_status" ] && echo "- Exit status: $exit_status"
    echo "- Reason: $reason"
    echo "- Transcript: ${CURRENT_TRANSCRIPT_FILE:-none}"
    echo "- Last message: ${CURRENT_LAST_MESSAGE_FILE:-none}"
    echo "- Run state: $STATE_FILE"
    echo "- Resume: rerun \`bash scripts/ralph/ralph.sh $TOOL 1\` after reviewing the current manager/worktree state."
    echo "- Rollback: not performed automatically; current workspace edits are preserved."
    echo "---"
  } >> "$PROGRESS_FILE"
}

print_failure_tail() {
  local transcript_file="$1"

  if [ -s "$transcript_file" ] && [ "$RALPH_FAILURE_TAIL_LINES" -gt 0 ]; then
    echo ""
    echo "Last $RALPH_FAILURE_TAIL_LINES transcript lines:"
    tail -n "$RALPH_FAILURE_TAIL_LINES" "$transcript_file"
  fi
}

write_last_message_snapshot() {
  local source_file="$1"
  local target_file="$2"

  if [ ! -f "$source_file" ]; then
    : > "$target_file"
    return 0
  fi

  awk -v keep="$RALPH_LAST_MESSAGE_LINES" '
    {
      lines[NR] = $0
      if ($0 ~ /[^[:space:]]/) {
        last_non_empty = NR
      }
    }
    END {
      if (!last_non_empty) {
        exit
      }

      start = last_non_empty - keep + 1
      if (start < 1) {
        start = 1
      }

      for (i = start; i <= last_non_empty; i++) {
        print lines[i]
      }
    }
  ' "$source_file" > "$target_file"
}

trim_transcript_log() {
  local transcript_file="$1"
  local line_count=""
  local tmp_file=""

  if [ ! -f "$transcript_file" ]; then
    return 0
  fi

  line_count="$(wc -l < "$transcript_file")"
  line_count="${line_count//[[:space:]]/}"

  if [ "$line_count" -le "$RALPH_TRANSCRIPT_MAX_LINES" ]; then
    return 0
  fi

  tmp_file="$(mktemp "$LOG_DIR/latest-transcript.XXXXXX")" || return 1

  if {
    echo "# Transcript truncated by Ralph"
    echo "# Original lines: $line_count"
    echo "# Kept latest lines: $RALPH_TRANSCRIPT_KEEP_LINES"
    echo "# Truncated at: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "---"
    tail -n "$RALPH_TRANSCRIPT_KEEP_LINES" "$transcript_file"
  } > "$tmp_file"; then
    mv "$tmp_file" "$transcript_file"
  else
    rm -f "$tmp_file"
    return 1
  fi
}

archive_current_logs() {
  local archived_transcript=""
  local archived_last_message=""

  if [ -z "$CURRENT_ITERATION" ] || [ -z "$CURRENT_LOG_TIMESTAMP" ]; then
    return 0
  fi

  mkdir -p "$FAILURE_LOG_DIR"

  case "$CURRENT_TRANSCRIPT_FILE" in
    "$FAILURE_LOG_DIR"/*)
      ;;
    *)
      if [ -f "$CURRENT_TRANSCRIPT_FILE" ]; then
        archived_transcript="$FAILURE_LOG_DIR/iteration-$CURRENT_ITERATION-$CURRENT_LOG_TIMESTAMP.log"
        cp "$CURRENT_TRANSCRIPT_FILE" "$archived_transcript"
        CURRENT_TRANSCRIPT_FILE="$archived_transcript"
      fi
      ;;
  esac

  case "$CURRENT_LAST_MESSAGE_FILE" in
    "$FAILURE_LOG_DIR"/*)
      ;;
    *)
      if [ -f "$CURRENT_LAST_MESSAGE_FILE" ]; then
        archived_last_message="$FAILURE_LOG_DIR/iteration-$CURRENT_ITERATION-$CURRENT_LOG_TIMESTAMP.last.txt"
        cp "$CURRENT_LAST_MESSAGE_FILE" "$archived_last_message"
        CURRENT_LAST_MESSAGE_FILE="$archived_last_message"
      fi
      ;;
  esac
}

stop_heartbeat() {
  if [ -n "$HEARTBEAT_PID" ] && kill -0 "$HEARTBEAT_PID" >/dev/null 2>&1; then
    kill "$HEARTBEAT_PID" >/dev/null 2>&1 || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
  fi
  HEARTBEAT_PID=""
}

start_heartbeat() {
  local iteration="$1"
  local transcript_file="$2"
  local started_at_epoch="$3"
  local interval="$RALPH_HEARTBEAT_SECONDS"

  if ! [[ "$interval" =~ ^[0-9]+$ ]] || [ "$interval" -le 0 ]; then
    return 0
  fi

  (
    while true; do
      sleep "$interval" || exit 0
      local now
      local elapsed
      now="$(date +%s)"
      elapsed=$((now - started_at_epoch))
      echo "Iteration $iteration/$MAX_ITERATIONS: still running (${elapsed}s elapsed). Transcript: $transcript_file"
      write_state "running" "agent still running; elapsed ${elapsed}s"
    done
  ) &
  HEARTBEAT_PID=$!
}

handle_signal() {
  local signal="$1"
  local exit_status=130

  if [ "$signal" = "SIGTERM" ]; then
    exit_status=143
  fi

  echo ""
  echo "Ralph interrupted by $signal. Stopping without rollback."
  stop_heartbeat
  archive_current_logs
  write_state "interrupted" "received $signal" "$exit_status"
  append_progress_event "interrupted" "received $signal" "$exit_status"
  print_failure_tail "$CURRENT_TRANSCRIPT_FILE"
  exit "$exit_status"
}

is_complete_signal_file() {
  local file="$1"

  if [ ! -s "$file" ]; then
    return 1
  fi

  # Prefer an exact final response match. As a fallback for tools that do not
  # expose a last-message file, accept only the final non-empty output line.
  local normalized
  normalized="$(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' "$file")"

  if [ "$normalized" = "$COMPLETE_SIGNAL" ]; then
    return 0
  fi

  local last_line
  last_line="$(printf '%s\n' "$normalized" | tail -n 1)"
  [ "$last_line" = "$COMPLETE_SIGNAL" ]
}

run_with_timeout() {
  if is_timeout_enabled && [ "$TIMEOUT_AVAILABLE" = "1" ]; then
    timeout "$RALPH_AGENT_TIMEOUT" "$@"
  else
    "$@"
  fi
}

run_agent_iteration() {
  local iteration="$1"
  local transcript_file="$2"
  local last_message_file="$3"
  local status=0
  local trim_status=0

  CURRENT_STARTED_AT_EPOCH="$(date +%s)"
  rm -f "$transcript_file" "$last_message_file"
  start_heartbeat "$iteration" "$transcript_file" "$CURRENT_STARTED_AT_EPOCH"

  set +e

  case "$TOOL" in
    claude)
      if [ "${RALPH_VERBOSE:-0}" = "1" ]; then
        (cd "$PROJECT_ROOT" && run_with_timeout claude --dangerously-skip-permissions --print < "$AGENT_FILE") 2>&1 | tee "$transcript_file"
        status=${PIPESTATUS[0]}
      else
        (cd "$PROJECT_ROOT" && run_with_timeout claude --dangerously-skip-permissions --print < "$AGENT_FILE") > "$transcript_file" 2>&1
        status=$?
      fi
      write_last_message_snapshot "$transcript_file" "$last_message_file"
      ;;
    codex)
      if [ "${RALPH_VERBOSE:-0}" = "1" ]; then
        run_with_timeout codex exec --dangerously-bypass-approvals-and-sandbox -C "$PROJECT_ROOT" -o "$last_message_file" - < "$AGENT_FILE" 2>&1 | tee "$transcript_file"
        status=${PIPESTATUS[0]}
      else
        run_with_timeout codex exec --dangerously-bypass-approvals-and-sandbox -C "$PROJECT_ROOT" -o "$last_message_file" - < "$AGENT_FILE" > "$transcript_file" 2>&1
        status=$?
      fi
      ;;
    opencode)
      if [ "${RALPH_VERBOSE:-0}" = "1" ]; then
        run_with_timeout opencode run --dir "$PROJECT_ROOT" --dangerously-skip-permissions "$(cat "$AGENT_FILE")" 2>&1 | tee "$transcript_file"
        status=${PIPESTATUS[0]}
      else
        run_with_timeout opencode run --dir "$PROJECT_ROOT" --dangerously-skip-permissions "$(cat "$AGENT_FILE")" > "$transcript_file" 2>&1
        status=$?
      fi
      write_last_message_snapshot "$transcript_file" "$last_message_file"
      ;;
  esac

  set -e
  stop_heartbeat

  if [ ! -f "$last_message_file" ]; then
    write_last_message_snapshot "$transcript_file" "$last_message_file" 2>/dev/null || touch "$last_message_file"
  fi

  trim_transcript_log "$transcript_file" || trim_status=$?

  set +e

  if [ "$status" -ne 0 ]; then
    return "$status"
  fi

  return "$trim_status"
}

agent_failure_reason() {
  local status="$1"

  if [ "$status" -eq 124 ] && is_timeout_enabled && [ "$TIMEOUT_AVAILABLE" = "1" ]; then
    echo "agent timed out after $RALPH_AGENT_TIMEOUT"
  else
    echo "$TOOL exited with status $status"
  fi
}

# Parse arguments
TOOL="codex"
MAX_ITERATIONS=10

while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      print_usage
      exit 0
      ;;
    --tool)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --tool requires one of: $SUPPORTED_TOOLS"
        exit 1
      fi
      TOOL="$2"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
      elif is_supported_tool "$1"; then
        TOOL="$1"
      else
        echo "Error: Unknown argument '$1'."
        print_usage
        exit 1
      fi
      shift
      ;;
  esac
done

# Validate tool choice
if ! is_supported_tool "$TOOL"; then
  echo "Error: Invalid tool '$TOOL'. Must be one of: $SUPPORTED_TOOLS"
  exit 1
fi

if [ ! -f "$AGENT_FILE" ]; then
  echo "Error: Missing agent instructions at $AGENT_FILE"
  exit 1
fi

if ! command -v "$TOOL" >/dev/null 2>&1; then
  echo "Error: '$TOOL' command not found in PATH."
  exit 1
fi

if ! [[ "$RALPH_HEARTBEAT_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "Error: RALPH_HEARTBEAT_SECONDS must be a non-negative integer."
  exit 1
fi

if ! [[ "$RALPH_FAILURE_TAIL_LINES" =~ ^[0-9]+$ ]]; then
  echo "Error: RALPH_FAILURE_TAIL_LINES must be a non-negative integer."
  exit 1
fi

if ! [[ "$RALPH_LAST_MESSAGE_LINES" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: RALPH_LAST_MESSAGE_LINES must be a positive integer."
  exit 1
fi

if ! [[ "$RALPH_TRANSCRIPT_MAX_LINES" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: RALPH_TRANSCRIPT_MAX_LINES must be a positive integer."
  exit 1
fi

if ! [[ "$RALPH_TRANSCRIPT_KEEP_LINES" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: RALPH_TRANSCRIPT_KEEP_LINES must be a positive integer."
  exit 1
fi

if [ "$RALPH_TRANSCRIPT_KEEP_LINES" -gt "$RALPH_TRANSCRIPT_MAX_LINES" ]; then
  echo "Error: RALPH_TRANSCRIPT_KEEP_LINES must be less than or equal to RALPH_TRANSCRIPT_MAX_LINES."
  exit 1
fi

if is_timeout_enabled; then
  if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_AVAILABLE=1
  else
    echo "Warning: timeout command not found; agent timeout disabled."
  fi
fi

# Initialize progress file if it doesn't exist
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
fi

mkdir -p "$LOG_DIR"
trap 'handle_signal SIGINT' INT
trap 'handle_signal SIGTERM' TERM

echo "Ralph Manager loop"
echo "- Tool: $TOOL"
echo "- Max iterations: $MAX_ITERATIONS"
echo "- Latest transcript: $LOG_DIR/latest-transcript.log"
echo "- Failure transcripts: $FAILURE_LOG_DIR"
echo "- State: $STATE_FILE"
echo "- Agent timeout: $(timeout_label)"
echo "- Heartbeat: ${RALPH_HEARTBEAT_SECONDS}s"
echo "- Verbose output: set RALPH_VERBOSE=1"
echo "- Manager current.title: $(manager_current_field title)"
echo "- Manager current.batch: $(manager_current_field batch)"
echo "- Manager current.wave: $(manager_current_field wave)"
echo "- Manager current.next: $(manager_current_field next)"

write_state "starting" "validated input; starting loop"

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "Iteration $i/$MAX_ITERATIONS: running $TOOL"

  TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
  TRANSCRIPT_FILE="$LOG_DIR/latest-transcript.log"
  LAST_MESSAGE_FILE="$LOG_DIR/latest.last.txt"
  CURRENT_ITERATION="$i"
  CURRENT_TRANSCRIPT_FILE="$TRANSCRIPT_FILE"
  CURRENT_LAST_MESSAGE_FILE="$LAST_MESSAGE_FILE"
  CURRENT_LOG_TIMESTAMP="$TIMESTAMP"

  echo "Iteration $i/$MAX_ITERATIONS: transcript -> $TRANSCRIPT_FILE"
  echo "Iteration $i/$MAX_ITERATIONS: last message -> $LAST_MESSAGE_FILE"
  write_state "running" "starting iteration $i"

  set +e
  run_agent_iteration "$i" "$TRANSCRIPT_FILE" "$LAST_MESSAGE_FILE"
  AGENT_STATUS=$?
  set -e

  if [ "$AGENT_STATUS" -ne 0 ]; then
    FAILURE_REASON="$(agent_failure_reason "$AGENT_STATUS")"
    echo "Iteration $i/$MAX_ITERATIONS: failed - $FAILURE_REASON"
    echo "Ralph stopped without rollback. Review the run state and transcript before rerunning."
    archive_current_logs
    write_state "failed" "$FAILURE_REASON" "$AGENT_STATUS"
    append_progress_event "failed" "$FAILURE_REASON" "$AGENT_STATUS"
    print_failure_tail "$TRANSCRIPT_FILE"
    exit "$AGENT_STATUS"
  fi

  echo "Iteration $i/$MAX_ITERATIONS: transcript saved to $TRANSCRIPT_FILE"
  write_state "checking-completion" "agent exited successfully; checking completion signal"
  
  # Check for completion signal
  if is_complete_signal_file "$LAST_MESSAGE_FILE"; then
    echo ""
    echo "Ralph completed all executable Manager waves!"
    echo "Completed at iteration $i of $MAX_ITERATIONS"
    write_state "completed" "completion signal received at iteration $i"
    exit 0
  fi
  
  echo "Iteration $i/$MAX_ITERATIONS: complete; continuing"
  write_state "iteration-complete" "iteration $i completed without completion signal"
  sleep 2
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS) without completing all tasks."
echo "Check $PROGRESS_FILE for status."
archive_current_logs
write_state "max-iterations" "reached max iterations without completion signal" "1"
append_progress_event "max-iterations" "reached max iterations without completion signal" "1"
exit 1
