import {
  Activity,
  Check,
  CircleAlert,
  CircleStop,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { ActiveRunConflict, ConfirmationRequest, RunStatus } from '../../model';
import styles from './ActiveRunBanner.module.css';

export type ActiveRunBannerProps = {
  canCancel: boolean;
  canReconnect: boolean;
  confirmation: ConfirmationRequest | null;
  conflict: ActiveRunConflict | null;
  isCancelling: boolean;
  isConfirming: boolean;
  onCancel: () => void;
  onConfirm: (approved: boolean) => void;
  onReconnect: () => void;
  status: RunStatus;
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

const descriptionKeys: Record<
  Extract<RunStatus, 'restoring' | 'starting' | 'running' | 'waiting_confirmation' | 'reconnecting'>,
  string
> = {
  restoring: 'agent.run.restoringDescription',
  starting: 'agent.run.startingDescription',
  running: 'agent.run.runningDescription',
  waiting_confirmation: 'agent.run.waitingConfirmationDescription',
  reconnecting: 'agent.run.reconnectingDescription',
};

type ActiveRunVariant =
  | 'conflict'
  | Extract<RunStatus, 'restoring' | 'starting' | 'running' | 'waiting_confirmation' | 'reconnecting'>;

function getVariant(
  conflict: ActiveRunConflict | null,
  status: RunStatus,
): ActiveRunVariant | null {
  if (conflict) return 'conflict';
  if (
    status === 'restoring' ||
    status === 'starting' ||
    status === 'running' ||
    status === 'waiting_confirmation' ||
    status === 'reconnecting'
  ) {
    return status;
  }
  return null;
}

export function ActiveRunBanner({
  canCancel,
  canReconnect,
  confirmation,
  conflict,
  isCancelling,
  isConfirming,
  onCancel,
  onConfirm,
  onReconnect,
  status,
}: ActiveRunBannerProps) {
  const { t } = useTranslation();
  const variant = getVariant(conflict, status);
  if (!variant) return null;

  const isRecoverable = variant === 'conflict' || variant === 'reconnecting';
  const Icon =
    variant === 'waiting_confirmation'
      ? ShieldAlert
      : isRecoverable
        ? CircleAlert
        : variant === 'running'
          ? Activity
          : LoaderCircle;
  const statusLabel =
    variant === 'conflict' ? t('agent.run.conflictStatus') : t(statusKeys[variant]);
  const description =
    variant === 'conflict'
      ? t('agent.run.activeConflict')
      : t(descriptionKeys[variant]);

  return (
    <section className={styles.root} data-variant={variant} role="status" aria-live="polite">
      <div className={styles.icon} aria-hidden="true">
        <Icon
          className={
            variant === 'restoring' || variant === 'starting' ? styles.spin : undefined
          }
          size={17}
        />
      </div>
      <div className={styles.content}>
        <strong>{statusLabel}</strong>
        <p>{description}</p>
        {conflict ? (
          <span className={styles.meta}>
            {t('agent.run.id')}: {conflict.activeRunId.slice(0, 12)}
          </span>
        ) : null}
        {variant === 'waiting_confirmation' && confirmation ? (
          <div className={styles.confirmation} aria-label={t('agent.run.confirmationLabel')}>
            <div className={styles.confirmationField}>
              <span className={styles.confirmationLabel}>
                {t('agent.run.confirmationCommand')}
              </span>
              <code>{confirmation.command}</code>
            </div>
            <div className={styles.confirmationField}>
              <span className={styles.confirmationLabel}>
                {t('agent.run.confirmationReason')}
              </span>
              <span>{confirmation.reason}</span>
            </div>
            <div className={styles.confirmationActions}>
              <button
                className={`${styles.action} ${styles.confirmAction}`}
                type="button"
                disabled={isConfirming || isCancelling}
                onClick={() => onConfirm(true)}
              >
                <Check size={15} aria-hidden="true" />
                {t('agent.run.confirm')}
              </button>
              <button
                className={`${styles.action} ${styles.rejectAction}`}
                type="button"
                disabled={isConfirming || isCancelling}
                onClick={() => onConfirm(false)}
              >
                <X size={15} aria-hidden="true" />
                {t('agent.run.reject')}
              </button>
            </div>
          </div>
        ) : null}
      </div>
      {isRecoverable && canReconnect ? (
        <button className={styles.action} type="button" onClick={onReconnect}>
          <RefreshCw size={15} aria-hidden="true" />
          {t('agent.run.reconnect')}
        </button>
      ) : null}
      {canCancel && !isRecoverable ? (
        <button
          className={`${styles.action} ${styles.cancelAction}`}
          type="button"
          disabled={isConfirming || isCancelling}
          onClick={onCancel}
        >
          <CircleStop size={15} aria-hidden="true" />
          {isCancelling ? t('agent.run.cancelling') : t('agent.run.cancel')}
        </button>
      ) : null}
    </section>
  );
}
