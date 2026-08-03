import { LoaderCircle, Play, RotateCcw } from 'lucide-react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import styles from './AgentComposer.module.css';

export type AgentComposerProps = {
  hasRun: boolean;
  isPending: boolean;
  task: string;
  onReset: () => void;
  onSubmit: () => void;
  onTaskChange: (task: string) => void;
};

export function AgentComposer({
  hasRun,
  isPending,
  task,
  onReset,
  onSubmit,
  onTaskChange,
}: AgentComposerProps) {
  const { t } = useTranslation();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isPending || !task.trim()) return;
    onSubmit();
  }

  return (
    <form className={styles.root} onSubmit={handleSubmit}>
      <div className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t('agent.composer.eyebrow')}</p>
          <h2 className={styles.title}>{t('agent.composer.title')}</h2>
        </div>
        <span className={styles.count}>{task.length}/4000</span>
      </div>

      <div className={styles.fieldGroup}>
        <label className={styles.label} htmlFor="agent-task">
          {t('agent.composer.label')}
        </label>
        <textarea
          id="agent-task"
          className={styles.textarea}
          value={task}
          maxLength={4000}
          rows={8}
          placeholder={t('agent.composer.placeholder')}
          onChange={(event) => onTaskChange(event.target.value)}
          disabled={isPending}
        />
      </div>

      <div className={styles.actions}>
        <button className={styles.primaryButton} type="submit" disabled={isPending || !task.trim()}>
          {isPending ? (
            <LoaderCircle className={styles.spin} size={17} aria-hidden="true" />
          ) : (
            <Play size={17} aria-hidden="true" />
          )}
          {isPending ? t('agent.composer.running') : t('agent.composer.run')}
        </button>
        {hasRun ? (
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onReset}
            disabled={isPending}
          >
            <RotateCcw size={16} aria-hidden="true" />
            {t('agent.composer.newRun')}
          </button>
        ) : null}
      </div>
    </form>
  );
}
