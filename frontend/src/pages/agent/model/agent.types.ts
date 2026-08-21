export const AGENT_EVENT_TYPES = [
  'text',
  'tool_call',
  'tool_result',
  'context_usage',
  'done',
] as const;

export const AGENT_TERMINAL_STATUSES = [
  'completed',
  'failed',
  'max_turns',
  'cancelled',
] as const;

export type AgentEventType = (typeof AGENT_EVENT_TYPES)[number];
export type AgentTerminalStatus = (typeof AGENT_TERMINAL_STATUSES)[number];
export type RunStatus =
  | 'idle'
  | 'starting'
  | 'running'
  | 'completed'
  | 'failed'
  | 'interrupted';

export type RunRequestDto = {
  task: string;
};

export type SessionDto = {
  session_id: string;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
};

export type RunCreatedDto = {
  run_id: string;
  session_id: string;
  message_id: string;
  status: string;
};

export type TextEventData = {
  turn: number;
  text: string;
};

export type ToolCallItem = {
  tool_use_id: string;
  name: string;
  arguments: string;
};

export type ToolCallEventData = {
  turn: number;
  calls: ToolCallItem[];
};

export type ToolResultItem = {
  tool_use_id: string;
  content: string;
};

export type ToolResultEventData = {
  turn: number;
  results: ToolResultItem[];
};

export type ContextUsageEventData = {
  turn: number;
  context_tokens: number | null;
  context_window_tokens: number;
  context_usage_percent: number | null;
  available: boolean;
};

export type DoneEventData = {
  status: AgentTerminalStatus;
  turn?: number;
  finish_reason?: string;
  error?: string;
  max_turns?: number;
};

type AgentEventDataByType = {
  text: TextEventData;
  tool_call: ToolCallEventData;
  tool_result: ToolResultEventData;
  context_usage: ContextUsageEventData;
  done: DoneEventData;
};

export type AgentEventDto = {
  [Event in AgentEventType]: {
    sequence: number;
    run_id: string;
    event: Event;
    data: AgentEventDataByType[Event];
  };
}[AgentEventType];

export type AgentEvent = {
  [Event in AgentEventType]: {
    sequence: number;
    runId: string;
    type: Event;
    data: AgentEventDataByType[Event];
  };
}[AgentEventType];

type UnknownRecord = Record<string, unknown>;

const AGENT_EVENT_TYPE_SET = new Set<string>(AGENT_EVENT_TYPES);
const AGENT_TERMINAL_STATUS_SET = new Set<string>(AGENT_TERMINAL_STATUSES);

function readRecord(value: unknown, label: string): UnknownRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as UnknownRecord;
}

function readString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function readStringValue(value: unknown, label: string): string {
  if (typeof value !== 'string') {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

function readInteger(value: unknown, label: string, minimum: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum) {
    throw new Error(`${label} must be an integer >= ${minimum}`);
  }
  return value;
}

function readNullableNumber(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== 'number' || value < 0) {
    throw new Error(`${label} must be null or a non-negative number`);
  }
  return value;
}

function readBoolean(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function readOptionalString(value: unknown, label: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  return readString(value, label);
}

function readOptionalInteger(
  value: unknown,
  label: string,
  minimum: number,
): number | undefined {
  if (value === undefined || value === null) return undefined;
  return readInteger(value, label, minimum);
}

function isAgentEventType(value: unknown): value is AgentEventType {
  return typeof value === 'string' && AGENT_EVENT_TYPE_SET.has(value);
}

function readTerminalStatus(value: unknown): AgentTerminalStatus {
  if (typeof value !== 'string' || !AGENT_TERMINAL_STATUS_SET.has(value)) {
    throw new Error('data.status is not a supported terminal status');
  }
  return value as AgentTerminalStatus;
}

function readToolCalls(value: unknown): ToolCallItem[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error('data.calls must be a non-empty array');
  }
  return value.map((item, index) => {
    const call = readRecord(item, `data.calls[${index}]`);
    return {
      tool_use_id: readString(call.tool_use_id, `data.calls[${index}].tool_use_id`),
      name: readString(call.name, `data.calls[${index}].name`),
      arguments: readStringValue(call.arguments, `data.calls[${index}].arguments`),
    };
  });
}

function readToolResults(value: unknown): ToolResultItem[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error('data.results must be a non-empty array');
  }
  return value.map((item, index) => {
    const result = readRecord(item, `data.results[${index}]`);
    return {
      tool_use_id: readString(result.tool_use_id, `data.results[${index}].tool_use_id`),
      content: readStringValue(result.content, `data.results[${index}].content`),
    };
  });
}

export function parseAgentEvent(value: unknown): AgentEvent {
  const envelope = readRecord(value, 'event');
  const sequence = readInteger(envelope.sequence, 'sequence', 0);
  const runId = readString(envelope.run_id, 'run_id');
  const eventType = envelope.event;
  if (!isAgentEventType(eventType)) {
    throw new Error('event is not a supported Agent Event type');
  }
  const data = readRecord(envelope.data, 'data');

  switch (eventType) {
    case 'text':
      return {
        sequence,
        runId,
        type: eventType,
        data: {
          turn: readInteger(data.turn, 'data.turn', 1),
          text: readString(data.text, 'data.text'),
        },
      };
    case 'tool_call':
      return {
        sequence,
        runId,
        type: eventType,
        data: {
          turn: readInteger(data.turn, 'data.turn', 1),
          calls: readToolCalls(data.calls),
        },
      };
    case 'tool_result':
      return {
        sequence,
        runId,
        type: eventType,
        data: {
          turn: readInteger(data.turn, 'data.turn', 1),
          results: readToolResults(data.results),
        },
      };
    case 'context_usage':
      return {
        sequence,
        runId,
        type: eventType,
        data: {
          turn: readInteger(data.turn, 'data.turn', 1),
          context_tokens: readNullableNumber(data.context_tokens, 'data.context_tokens'),
          context_window_tokens: readInteger(
            data.context_window_tokens,
            'data.context_window_tokens',
            1,
          ),
          context_usage_percent: readNullableNumber(
            data.context_usage_percent,
            'data.context_usage_percent',
          ),
          available: readBoolean(data.available, 'data.available'),
        },
      };
    case 'done': {
      const status = readTerminalStatus(data.status);
      const maxTurns = readOptionalInteger(data.max_turns, 'data.max_turns', 1);
      if (status === 'max_turns' && maxTurns === undefined) {
        throw new Error('max_turns terminal status requires data.max_turns');
      }
      return {
        sequence,
        runId,
        type: eventType,
        data: {
          status,
          turn: readOptionalInteger(data.turn, 'data.turn', 0),
          finish_reason: readOptionalString(data.finish_reason, 'data.finish_reason'),
          error: readOptionalString(data.error, 'data.error'),
          max_turns: maxTurns,
        },
      };
    }
  }

  const unsupportedEventType: never = eventType;
  throw new Error(`unsupported Agent Event type: ${unsupportedEventType}`);
}

export function toRunStatus(
  value: AgentTerminalStatus,
): Exclude<RunStatus, 'idle' | 'starting' | 'running'> {
  if (value === 'completed') return 'completed';
  if (value === 'cancelled') return 'interrupted';
  return 'failed';
}
