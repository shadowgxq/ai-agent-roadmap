import { LoaderCircle, Play, RotateCcw } from 'lucide-react';
import type { FormEvent, KeyboardEvent } from 'react';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import styles from './AgentComposer.module.css';

const MAX_TASK_LENGTH = 4000;
const MAX_TEXTAREA_HEIGHT = 220;

export type AgentComposerProps = {
  hasSession: boolean;
  isPending: boolean;
  task: string;
  onReset: () => void;
  onSubmit: () => void;
  onTaskChange: (task: string) => void;
};

export function AgentComposer({
  hasSession,
  isPending,
  task,
  onReset,
  onSubmit,
  onTaskChange,
}: AgentComposerProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_TEXTAREA_HEIGHT ? 'auto' : 'hidden';
  }, [task]);

  function submitTask() {
    if (isPending || !task.trim()) return;
    onSubmit();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitTask();
  }

  function handleTaskKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      isPending
    ) {
      return;
    }

    event.preventDefault();
    submitTask();
  }

  return (
    <form className={styles.root} onSubmit={handleSubmit} aria-busy={isPending}>
      <div className={styles.header}>
        <div className={styles.heading}>
          <p className={styles.eyebrow}>{t('agent.composer.eyebrow')}</p>
          <h2 className={styles.title}>{t('agent.composer.title')}</h2>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.count}>
            {task.length}/{MAX_TASK_LENGTH}
          </span>
          {hasSession ? (
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onReset}
              disabled={isPending}
            >
              <RotateCcw size={15} aria-hidden="true" />
              {t('agent.composer.newSession')}
            </button>
          ) : null}
        </div>
      </div>

      <div className={styles.fieldGroup}>
        <div className={styles.inputMeta}>
          <label className={styles.label} htmlFor="agent-task">
            {t('agent.composer.label')}
          </label>
          <span className={styles.statusHint} aria-live="polite">
            {isPending ? t('agent.composer.running') : t('agent.composer.ready')}
          </span>
        </div>
        <div className={styles.inputShell} data-pending={isPending}>
          <textarea
            ref={textareaRef}
            id="agent-task"
            className={styles.textarea}
            value={task}
            maxLength={MAX_TASK_LENGTH}
            rows={1}
            placeholder={t('agent.composer.placeholder')}
            aria-describedby="agent-task-hint agent-task-shortcuts"
            onChange={(event) => onTaskChange(event.target.value)}
            onKeyDown={handleTaskKeyDown}
            disabled={isPending}
          />
          <div className={styles.inputFooter}>
            <span className={styles.helper} id="agent-task-hint">
              {t('agent.composer.helper')}
            </span>
            <button
              className={styles.primaryButton}
              type="submit"
              disabled={isPending || !task.trim()}
              aria-busy={isPending}
            >
              {isPending ? (
                <LoaderCircle className={styles.spin} size={17} aria-hidden="true" />
              ) : (
                <Play size={17} aria-hidden="true" />
              )}
              <span>{isPending ? t('agent.composer.running') : t('agent.composer.run')}</span>
            </button>
          </div>
        </div>
        <p className={styles.shortcuts} id="agent-task-shortcuts">
          {t('agent.composer.shortcuts')}
        </p>
      </div>
    </form>
  );
}
