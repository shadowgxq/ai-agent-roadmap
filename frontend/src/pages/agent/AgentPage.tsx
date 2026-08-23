import { Activity, Bot, CircleAlert, History } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useAgentHistory, useAgentRun, type RunStatus } from './model';
import { ActiveRunBanner } from './ui/ActiveRunBanner';
import { AgentComposer } from './ui/AgentComposer';
import { RunTimeline } from './ui/RunTimeline';
import { SessionDetail } from './ui/SessionDetail';
import { SessionHistory } from './ui/SessionHistory';
import styles from './AgentPage.module.css';

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

export function AgentPage() {
  const { t } = useTranslation();
  const [task, setTask] = useState('');
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const shouldFocusDetailRef = useRef(false);
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);
  const {
    canReconnect,
    cancelRun,
    confirmation,
    conflict,
    error,
    events,
    isPending,
    isCancelling,
    isConfirming,
    confirmRun,
    reconnectActiveRun,
    resetRun,
    resumeSession,
    runId,
    sessionId,
    startRun,
    status,
  } = useAgentRun();
  const {
    clearSelection,
    detail,
    error: historyError,
    isLoading: isHistoryLoading,
    refresh: refreshHistory,
    refreshDetail: refreshHistoryDetail,
    selectSession,
    selectedSessionId,
    sessions,
  } = useAgentHistory();
  const requestedSessionId = searchParams.get('sessionId');
  const requestedRunId = searchParams.get('runId');
  const selectedRunId =
    detail?.runs.some((run) => run.runId === requestedRunId) ? requestedRunId : null;

  useEffect(() => {
    if (!sessionId || !isPending || isHistoryLoading || selectedSessionId === sessionId) {
      return;
    }

    shouldFocusDetailRef.current = false;
    selectSession(sessionId);
  }, [isHistoryLoading, isPending, selectSession, selectedSessionId, sessionId]);

  useEffect(() => {
    if (
      !requestedSessionId ||
      isHistoryLoading ||
      selectedSessionId === requestedSessionId ||
      !sessions.some((session) => session.sessionId === requestedSessionId)
    ) {
      return;
    }

    selectSession(requestedSessionId);
  }, [isHistoryLoading, requestedSessionId, selectSession, selectedSessionId, sessions]);

  useEffect(() => {
    if (!sessionId || !['completed', 'failed', 'interrupted'].includes(status)) return;
    void refreshHistory(sessionId);
  }, [refreshHistory, sessionId, status]);

  useEffect(() => {
    if (!sessionId || !isPending) return;

    void refreshHistoryDetail(sessionId);
    const refreshTimer = window.setInterval(() => {
      void refreshHistoryDetail(sessionId);
    }, 1500);

    return () => window.clearInterval(refreshTimer);
  }, [isPending, refreshHistoryDetail, sessionId]);

  useEffect(() => {
    if (
      !shouldFocusDetailRef.current ||
      !detail ||
      detail.session.sessionId !== selectedSessionId
    ) {
      return;
    }

    shouldFocusDetailRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      detailHeadingRef.current?.scrollIntoView({ block: 'start' });
      detailHeadingRef.current?.focus({ preventScroll: true });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [detail, selectedSessionId]);

  function updateSessionQuery(nextSessionId: string | null, nextRunId: string | null = null) {
    setSearchParams(
      (currentParams) => {
        if (nextSessionId) {
          currentParams.set('sessionId', nextSessionId);
        } else {
          currentParams.delete('sessionId');
        }
        if (nextRunId) {
          currentParams.set('runId', nextRunId);
        } else {
          currentParams.delete('runId');
        }
        return currentParams;
      },
      { replace: true },
    );
  }

  function handleSubmit() {
    void startRun(task);
  }

  function handleReset() {
    resetRun();
    clearSelection();
    updateSessionQuery(null);
  }

  function handleSelectSession(nextSessionId: string) {
    if (isPending && nextSessionId !== sessionId) return;

    shouldFocusDetailRef.current = true;
    setIsHistoryOpen(false);
    selectSession(nextSessionId);
    updateSessionQuery(nextSessionId);
    if (!isPending || nextSessionId !== sessionId) {
      resumeSession(nextSessionId);
    }
  }

  function handleSelectRun(nextRunId: string) {
    if (!detail?.runs.some((run) => run.runId === nextRunId)) return;
    updateSessionQuery(detail.session.sessionId, nextRunId);
  }

  const hasLiveTimeline = isPending || events.length > 0;

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <header className={styles.header}>
          <div className={styles.identity}>
            <span className={styles.identityIcon} aria-hidden="true">
              <Bot size={19} />
            </span>
            <div>
              <p className={styles.eyebrow}>{t('agent.eyebrow')}</p>
              <h1 className={styles.title}>{t('agent.title')}</h1>
            </div>
          </div>
          <div className={styles.status} data-status={status} aria-live="polite">
            <Activity size={15} aria-hidden="true" />
            <span>{t(statusKeys[status])}</span>
          </div>
        </header>

        <div className={styles.workspace}>
          <div
            className={styles.sidePanel}
            data-mobile-open={isHistoryOpen}
            id="agent-session-history"
          >
            <SessionHistory
              activeSessionId={sessionId}
              activeRunStatus={status}
              error={historyError}
              isLoading={isHistoryLoading}
              isRunPending={isPending}
              onCloseMobile={() => setIsHistoryOpen(false)}
              onRefresh={() => void refreshHistory(sessionId ?? undefined)}
              onSelectSession={handleSelectSession}
              selectedSessionId={selectedSessionId}
              sessions={sessions}
            />
          </div>

          <section className={styles.contentPanel} aria-label={t('agent.run.label')}>
            <div className={styles.contentScroll}>
              <header className={styles.contentHeader}>
                <button
                  className={styles.historyToggle}
                  type="button"
                  onClick={() => setIsHistoryOpen(true)}
                  aria-expanded={isHistoryOpen}
                  aria-controls="agent-session-history"
                >
                  <History size={16} aria-hidden="true" />
                  {t('agent.history.open')}
                </button>
                <div className={styles.runMeta}>
                  <div>
                    <p className={styles.eyebrow}>{t('agent.run.eyebrow')}</p>
                    <h2
                      className={styles.sessionTitle}
                      id="agent-session-detail-title"
                      ref={detailHeadingRef}
                      tabIndex={-1}
                    >
                      {detail
                        ? detail.session.sessionId.slice(0, 12)
                        : t('agent.history.selectTitle')}
                    </h2>
                    <p className={styles.sessionId}>
                      {sessionId
                        ? `${t('agent.run.sessionId')}: ${sessionId}`
                        : t('agent.run.sessionNotStarted')}
                    </p>
                    <p className={styles.runId}>
                      {runId ? `${t('agent.run.id')}: ${runId}` : t('agent.run.notStarted')}
                    </p>
                  </div>
                  {isPending ? <span className={styles.liveMark}>{t('agent.run.live')}</span> : null}
                </div>
              </header>

              {!detail && !isHistoryLoading ? (
                <p className={styles.selectDescription}>{t('agent.history.selectDescription')}</p>
              ) : null}

              <div className={styles.feedbackStack}>
                {error ? (
                  <div className={styles.error} role="alert">
                    <CircleAlert size={17} aria-hidden="true" />
                    <span>{error}</span>
                  </div>
                ) : null}
                <ActiveRunBanner
                  canCancel={Boolean(runId) && isPending && !conflict}
                  canReconnect={canReconnect}
                  confirmation={confirmation}
                  conflict={conflict}
                  isCancelling={isCancelling}
                  isConfirming={isConfirming}
                  onCancel={() => void cancelRun()}
                  onConfirm={(approved) => void confirmRun(approved)}
                  onReconnect={() => void reconnectActiveRun()}
                  status={status}
                />
              </div>

              {hasLiveTimeline ? <RunTimeline events={events} /> : null}
              {detail ? (
                <SessionDetail
                  detail={detail}
                  isLoading={isHistoryLoading}
                  onSelectRun={handleSelectRun}
                  selectedRunId={selectedRunId}
                />
              ) : !hasLiveTimeline ? (
                <RunTimeline events={events} />
              ) : null}
            </div>

            <div className={styles.composerDock}>
              <AgentComposer
                hasSession={Boolean(sessionId)}
                isPending={isPending}
                task={task}
                onReset={handleReset}
                onSubmit={handleSubmit}
                onTaskChange={setTask}
              />
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
