import { ArrowLeft, CircleAlert, History, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { AgentSession, RunStatus } from '../../model';
import styles from './SessionHistory.module.css';

export type SessionHistoryProps = {
  activeSessionId: string | null;
  activeRunStatus: RunStatus;
  error: string | null;
  isLoading: boolean;
  isRunPending: boolean;
  onCloseMobile: () => void;
  onRefresh: () => void;
  onSelectSession: (sessionId: string) => void;
  selectedSessionId: string | null;
  sessions: AgentSession[];
};

const statusKeys: Record<RunStatus, string> = {
  idle: 'agent.status.idle',
  restoring: 'agent.status.restoring',
  starting: 'agent.status.starting',
  running: 'agent.status.running',
  waiting_confirmation: 'agent.status.waitingConfirmation',
  reconnecting: 'agent.status.reconnecting',
  completed: 'agent.status.completed',
  failed: 'agent.status.failed',
  interrupted: 'agent.status.interrupted',
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function SessionHistory({
  activeSessionId,
  activeRunStatus,
  error,
  isLoading,
  isRunPending,
  onCloseMobile,
  onRefresh,
  onSelectSession,
  selectedSessionId,
  sessions,
}: SessionHistoryProps) {
  const { t } = useTranslation();

  return (
    <aside className={styles.root} aria-label={t('agent.history.label')} aria-busy={isLoading}>
      <header className={styles.header}>
        <div className={styles.headingIdentity}>
          <History size={17} aria-hidden="true" />
          <div>
            <p className={styles.eyebrow}>{t('agent.history.eyebrow')}</p>
            <h2 className={styles.title}>{t('agent.history.title')}</h2>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button
            className={styles.mobileClose}
            type="button"
            onClick={onCloseMobile}
            aria-label={t('agent.history.close')}
          >
            <ArrowLeft size={16} aria-hidden="true" />
          </button>
          <button
            className={styles.refresh}
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            aria-label={t('agent.history.refresh')}
          >
            <RefreshCw className={isLoading ? styles.spin : undefined} size={15} aria-hidden="true" />
            <span className={styles.refreshLabel}>{t('agent.history.refreshAction')}</span>
          </button>
        </div>
      </header>

      {isLoading ? (
        <p className={styles.loadingMessage} role="status">
          {t('agent.history.loading')}
        </p>
      ) : null}

      {error ? (
        <div className={styles.error} role="alert">
          <CircleAlert size={15} aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      {activeSessionId && activeRunStatus !== 'idle' ? (
        <div className={styles.activeHint} role="status" aria-live="polite">
          <span className={styles.activeDot} aria-hidden="true" />
          <span>{t(statusKeys[activeRunStatus])}</span>
          <span className={styles.activeHintLabel}>{t('agent.history.activeHint')}</span>
        </div>
      ) : null}

      <ul className={styles.sessionList} aria-label={t('agent.history.sessions')}>
        {sessions.length > 0 ? (
          sessions.map((session) => {
            const isActive = session.sessionId === activeSessionId;
            const isSelected = session.sessionId === selectedSessionId;
            const isSelectionDisabled = isRunPending && !isActive;

            return (
              <li key={session.sessionId}>
                <button
                  className={styles.sessionButton}
                  data-selected={isSelected}
                  type="button"
                  onClick={() => onSelectSession(session.sessionId)}
                  disabled={isLoading || isSelectionDisabled}
                  aria-pressed={isSelected}
                >
                  <span className={styles.sessionContent}>
                    <span className={styles.sessionName}>{session.sessionId.slice(0, 8)}</span>
                    {isActive && activeRunStatus !== 'idle' ? (
                      <span className={styles.sessionStatus} data-status={activeRunStatus}>
                        {t(statusKeys[activeRunStatus])}
                      </span>
                    ) : null}
                  </span>
                  <time dateTime={session.updatedAt}>{formatDate(session.updatedAt)}</time>
                </button>
              </li>
            );
          })
        ) : (
          <li>
            <p className={styles.empty}>
              {isLoading ? t('agent.history.loading') : t('agent.history.empty')}
            </p>
          </li>
        )}
      </ul>
    </aside>
  );
}
