import { Activity, Bot, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useAgentRun, type RunStatus } from './model';
import { AgentComposer } from './ui/AgentComposer';
import { RunTimeline } from './ui/RunTimeline';
import styles from './AgentPage.module.css';

const statusKeys: Record<RunStatus, string> = {
  idle: 'agent.status.idle',
  starting: 'agent.status.starting',
  running: 'agent.status.running',
  completed: 'agent.status.completed',
  failed: 'agent.status.failed',
  interrupted: 'agent.status.interrupted',
};

export function AgentPage() {
  const { t } = useTranslation();
  const [task, setTask] = useState('');
  const { error, events, isPending, resetRun, runId, sessionId, startRun, status } = useAgentRun();

  function handleSubmit() {
    void startRun(task);
  }

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
          <AgentComposer
            hasRun={Boolean(runId)}
            isPending={isPending}
            task={task}
            onReset={resetRun}
            onSubmit={handleSubmit}
            onTaskChange={setTask}
          />

          <section className={styles.runPanel} aria-label={t('agent.run.label')}>
            <div className={styles.runMeta}>
              <div>
                <p className={styles.eyebrow}>{t('agent.run.eyebrow')}</p>
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
            {error ? (
              <div className={styles.error} role="alert">
                <CircleAlert size={17} aria-hidden="true" />
                <span>{error}</span>
              </div>
            ) : null}
            <RunTimeline events={events} />
          </section>
        </div>
      </main>
    </div>
  );
}
