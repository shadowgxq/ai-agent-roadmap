import { CircleAlert, History, ListTree } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import type {
  AgentMessage,
  DiffFileItem,
  AgentSessionDetail,
  StoredRunStatus,
} from '../../model';
import { DiffView } from '../DiffView';
import styles from './SessionDetail.module.css';

export type SessionDetailProps = {
  detail: AgentSessionDetail;
  isLoading?: boolean;
  onSelectRun: (runId: string) => void;
  selectedRunId: string | null;
};

const roleKeys: Record<AgentMessage['role'], string> = {
  user: 'agent.history.roles.user',
  assistant: 'agent.history.roles.assistant',
  tool: 'agent.history.roles.tool',
};

const runStatusKeys: Record<StoredRunStatus, string> = {
  queued: 'agent.history.status.queued',
  running: 'agent.history.status.running',
  waiting_confirmation: 'agent.history.status.waitingConfirmation',
  completed: 'agent.history.status.completed',
  failed: 'agent.history.status.failed',
  max_turns: 'agent.history.status.maxTurns',
  cancelled: 'agent.history.status.cancelled',
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function isDiffFileItem(value: unknown): value is DiffFileItem {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const file = value as Record<string, unknown>;
  return (
    typeof file.path === 'string' &&
    (file.status === 'added' ||
      file.status === 'modified' ||
      file.status === 'deleted' ||
      file.status === 'binary') &&
    typeof file.patch === 'string' &&
    typeof file.additions === 'number' &&
    typeof file.deletions === 'number' &&
    typeof file.binary === 'boolean' &&
    typeof file.truncated === 'boolean'
  );
}

function parseStoredDiff(content: string): DiffFileItem[] | null {
  try {
    const value: unknown = JSON.parse(content);
    if (!Array.isArray(value) || value.length === 0 || !value.every(isDiffFileItem)) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

function MessageContent({ message }: { message: AgentMessage }) {
  if (message.kind === 'text') {
    return <p className={styles.messageContent}>{message.content}</p>;
  }

  if (message.kind === 'diff') {
    const files = parseStoredDiff(message.content);
    if (files) return <DiffView files={files} />;
  }

  return <pre className={styles.messageCode}>{message.content}</pre>;
}

export function SessionDetail({
  detail,
  isLoading = false,
  onSelectRun,
  selectedRunId,
}: SessionDetailProps) {
  const { t } = useTranslation();
  const selectedRunRef = useRef<HTMLButtonElement>(null);
  const lastFocusedRunIdRef = useRef<string | null>(null);
  const selectedRun = detail.runs.find((run) => run.runId === selectedRunId) ?? null;
  const visibleMessages = selectedRunId
    ? detail.messages.filter((message) => message.runId === selectedRunId)
    : detail.messages;

  useEffect(() => {
    if (!selectedRunId) {
      lastFocusedRunIdRef.current = null;
      return;
    }
    if (!selectedRun || selectedRunId === lastFocusedRunIdRef.current) return;

    lastFocusedRunIdRef.current = selectedRunId;
    const frame = window.requestAnimationFrame(() => {
      selectedRunRef.current?.scrollIntoView({ block: 'nearest' });
      selectedRunRef.current?.focus({ preventScroll: true });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [selectedRun, selectedRunId]);

  return (
    <section
      className={styles.root}
      aria-labelledby="agent-session-detail-content-title"
      aria-busy={isLoading}
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t('agent.history.detailEyebrow')}</p>
          <h2 className={styles.title} id="agent-session-detail-content-title">
            {detail.session.sessionId.slice(0, 12)}
          </h2>
          <p className={styles.sessionId}>{detail.session.sessionId}</p>
        </div>
        <span className={styles.detailCount}>
          {detail.runs.length} {t('agent.history.runCount')}
        </span>
      </header>

      <div className={styles.section}>
        <div className={styles.sectionHeading}>
          <ListTree size={16} aria-hidden="true" />
          <h3>{t('agent.history.runs')}</h3>
        </div>
        {detail.runs.length > 0 ? (
          <ul className={styles.runList}>
            {detail.runs.map((run) => {
              const isSelected = run.runId === selectedRunId;
              return (
                <li key={run.runId}>
                  <button
                    ref={isSelected ? selectedRunRef : undefined}
                    className={styles.runItem}
                    data-selected={isSelected}
                    type="button"
                    onClick={() => onSelectRun(run.runId)}
                    aria-pressed={isSelected}
                  >
                    <span className={styles.runItemHeader}>
                      <span className={styles.runStatus} data-status={run.status}>
                        {t(runStatusKeys[run.status])}
                      </span>
                      <time dateTime={run.createdAt}>{formatDate(run.createdAt)}</time>
                    </span>
                    <span className={styles.runTask}>{run.task}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={styles.empty}>{t('agent.history.noRuns')}</p>
        )}
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeading}>
          <History size={16} aria-hidden="true" />
          <h3>{t('agent.history.messages')}</h3>
        </div>
        {visibleMessages.length > 0 ? (
          <ol className={styles.messageList}>
            {visibleMessages.map((message) => (
              <li className={styles.messageItem} data-role={message.role} key={message.messageId}>
                <div className={styles.messageHeader}>
                  <span>{t(roleKeys[message.role])}</span>
                  <time dateTime={message.createdAt}>{formatDate(message.createdAt)}</time>
                </div>
                <MessageContent message={message} />
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.empty}>
            <CircleAlert size={15} aria-hidden="true" />
            {t('agent.history.noMessages')}
          </p>
        )}
      </div>
    </section>
  );
}
