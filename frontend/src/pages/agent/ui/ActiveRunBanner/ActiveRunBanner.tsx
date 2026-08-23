import { Activity, CircleAlert, LoaderCircle, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { ActiveRunConflict, RunStatus } from '../../model';
import styles from './ActiveRunBanner.module.css';

export type ActiveRunBannerProps = {
  canReconnect: boolean;
  conflict: ActiveRunConflict | null;
  onReconnect: () => void;
  status: RunStatus;
};

const statusKeys: Record<RunStatus, string> = {
  idle: 'agent.status.idle',
  restoring: 'agent.status.restoring',
  starting: 'agent.status.starting',
  running: 'agent.status.running',
  reconnecting: 'agent.status.reconnecting',
  completed: 'agent.status.completed',
  failed: 'agent.status.failed',
  interrupted: 'agent.status.interrupted',
};

const descriptionKeys: Record<
  Extract<RunStatus, 'restoring' | 'starting' | 'running' | 'reconnecting'>,
  string
> = {
  restoring: 'agent.run.restoringDescription',
  starting: 'agent.run.startingDescription',
  running: 'agent.run.runningDescription',
  reconnecting: 'agent.run.reconnectingDescription',
};

function getVariant(
  conflict: ActiveRunConflict | null,
  status: RunStatus,
): 'conflict' | Extract<RunStatus, 'restoring' | 'starting' | 'running' | 'reconnecting'> | null {
  if (conflict) return 'conflict';
  if (
    status === 'restoring' ||
    status === 'starting' ||
    status === 'running' ||
    status === 'reconnecting'
  ) {
    return status;
  }
  return null;
}

export function ActiveRunBanner({
  canReconnect,
  conflict,
  onReconnect,
  status,
}: ActiveRunBannerProps) {
  const { t } = useTranslation();
  const variant = getVariant(conflict, status);
  if (!variant) return null;

  const isRecoverable = variant === 'conflict' || variant === 'reconnecting';
  const Icon = isRecoverable ? CircleAlert : variant === 'running' ? Activity : LoaderCircle;
  const statusLabel =
    variant === 'conflict' ? t('agent.run.conflictStatus') : t(statusKeys[variant]);
  const description =
    variant === 'conflict'
      ? t('agent.run.activeConflict')
      : t(descriptionKeys[variant]);

  return (
    <section className={styles.root} data-variant={variant} role="status" aria-live="polite">
      <div className={styles.icon} aria-hidden="true">
        <Icon className={variant === 'restoring' || variant === 'starting' ? styles.spin : undefined} size={17} />
      </div>
      <div className={styles.content}>
        <strong>{statusLabel}</strong>
        <p>{description}</p>
        {conflict ? (
          <span className={styles.meta}>
            {t('agent.run.id')}: {conflict.activeRunId.slice(0, 12)}
          </span>
        ) : null}
      </div>
      {isRecoverable && canReconnect ? (
        <button className={styles.action} type="button" onClick={onReconnect}>
          <RefreshCw size={15} aria-hidden="true" />
          {t('agent.run.reconnect')}
        </button>
      ) : null}
    </section>
  );
}
