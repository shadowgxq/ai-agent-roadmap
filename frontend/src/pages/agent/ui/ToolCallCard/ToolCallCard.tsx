import { AlertCircle, CheckCircle2, LoaderCircle, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { ToolCallCardModel, ToolCallStatus, ToolCallWarning } from '../../model';
import styles from './ToolCallCard.module.css';

export type ToolCallCardProps = {
  tool: ToolCallCardModel;
};

const statusKeys: Record<ToolCallStatus, string> = {
  running: 'agent.tool.status.running',
  success: 'agent.tool.status.success',
  failed: 'agent.tool.status.failed',
};

const warningKeys: Record<ToolCallWarning, string> = {
  missing_call: 'agent.tool.warning.missingCall',
  missing_result: 'agent.tool.warning.missingResult',
  duplicate_call: 'agent.tool.warning.duplicateCall',
  duplicate_result: 'agent.tool.warning.duplicateResult',
};

function StatusIcon({ status }: { status: ToolCallStatus }) {
  if (status === 'running') {
    return <LoaderCircle className={styles.spin} size={15} aria-hidden="true" />;
  }
  if (status === 'success') {
    return <CheckCircle2 size={15} aria-hidden="true" />;
  }
  return <AlertCircle size={15} aria-hidden="true" />;
}

export function ToolCallCard({ tool }: ToolCallCardProps) {
  const { t } = useTranslation();
  const toolName = tool.call?.name ?? t('agent.tool.unknownName');

  return (
    <article className={styles.card} data-status={tool.status}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <span className={styles.icon} aria-hidden="true">
            <Wrench size={15} />
          </span>
          <div>
            <p className={styles.eyebrow}>{t('agent.tool.eyebrow')}</p>
            <h3 className={styles.name}>{toolName}</h3>
          </div>
        </div>
        <span className={styles.status} data-status={tool.status}>
          <StatusIcon status={tool.status} />
          {t(statusKeys[tool.status])}
        </span>
      </header>

      <p className={styles.toolId}>
        {t('agent.tool.id')}: {tool.toolUseId}
      </p>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>{t('agent.tool.arguments')}</p>
        <pre className={styles.code}>
          {tool.call?.arguments ?? t('agent.tool.missingCall')}
        </pre>
      </div>

      {tool.result ? (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>{t('agent.tool.result')}</p>
          <pre className={styles.result} data-error={tool.result.is_error}>
            {tool.result.content}
          </pre>
        </div>
      ) : (
        <p className={styles.waiting}>{t('agent.tool.waiting')}</p>
      )}

      {tool.warning ? (
        <p className={styles.warning} role="alert">
          <AlertCircle size={15} aria-hidden="true" />
          {t(warningKeys[tool.warning])}
        </p>
      ) : null}
    </article>
  );
}
