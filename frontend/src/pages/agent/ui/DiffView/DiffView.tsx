import {
  Binary,
  ChevronDown,
  ChevronRight,
  FileCode2,
  FilePlus2,
  FileX2,
  GitCompareArrows,
} from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { DiffFileItem, DiffStatus } from '../../model';
import styles from './DiffView.module.css';

type DiffViewProps = {
  files: DiffFileItem[];
};

const statusKeys: Record<DiffStatus, string> = {
  added: 'agent.diff.status.added',
  modified: 'agent.diff.status.modified',
  deleted: 'agent.diff.status.deleted',
  binary: 'agent.diff.status.binary',
};

function fileIcon(status: DiffStatus) {
  if (status === 'added') return <FilePlus2 size={15} aria-hidden="true" />;
  if (status === 'deleted') return <FileX2 size={15} aria-hidden="true" />;
  if (status === 'binary') return <Binary size={15} aria-hidden="true" />;
  return <FileCode2 size={15} aria-hidden="true" />;
}

function lineKind(line: string) {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'addition';
  if (line.startsWith('-') && !line.startsWith('---')) return 'deletion';
  if (line.startsWith('@@')) return 'hunk';
  return 'context';
}

function DiffPatch({ patch }: { patch: string }) {
  return (
    <pre className={styles.patch} tabIndex={0}>
      <code>
        {patch.split('\n').map((line, lineIndex) => (
          <span className={styles.patchLine} data-kind={lineKind(line)} key={`${lineIndex}-${line}`}>
            {line || ' '}
          </span>
        ))}
      </code>
    </pre>
  );
}

export function DiffView({ files }: DiffViewProps) {
  const { t } = useTranslation();
  const viewId = useId().replaceAll(':', '');
  const [expandedFiles, setExpandedFiles] = useState<Set<number>>(
    () => new Set(files.length > 0 ? [0] : []),
  );

  function toggleFile(index: number) {
    setExpandedFiles((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function selectFile(index: number) {
    setExpandedFiles((current) => new Set(current).add(index));
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.getElementById(`${viewId}-file-${index}`)?.scrollIntoView({
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
      block: 'nearest',
    });
  }

  if (files.length === 0) return null;

  return (
    <section className={styles.root} aria-labelledby={`${viewId}-title`}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <span className={styles.icon} aria-hidden="true">
            <GitCompareArrows size={16} />
          </span>
          <div>
            <p className={styles.eyebrow}>{t('agent.diff.eyebrow')}</p>
            <h3 className={styles.title} id={`${viewId}-title`}>
              {t('agent.diff.title')}
            </h3>
          </div>
        </div>
        <span className={styles.count}>{t('agent.diff.fileCount', { count: files.length })}</span>
      </header>

      <nav className={styles.fileList} aria-label={t('agent.diff.fileList')}>
        {files.map((file, index) => (
          <button
            className={styles.fileButton}
            key={`${file.path}-${index}`}
            type="button"
            onClick={() => selectFile(index)}
            aria-controls={`${viewId}-file-${index}`}
            aria-expanded={expandedFiles.has(index)}
          >
            {fileIcon(file.status)}
            <span>{file.path}</span>
          </button>
        ))}
      </nav>

      <div className={styles.files}>
        {files.map((file, index) => {
          const isExpanded = expandedFiles.has(index);
          const fileId = `${viewId}-file-${index}`;
          return (
            <article className={styles.file} id={fileId} key={fileId}>
              <button
                className={styles.fileHeader}
                type="button"
                onClick={() => toggleFile(index)}
                aria-expanded={isExpanded}
                aria-controls={`${fileId}-content`}
              >
                <span className={styles.fileIdentity}>
                  <span className={styles.chevron} aria-hidden="true">
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </span>
                  <span className={styles.statusIcon} data-status={file.status} aria-hidden="true">
                    {fileIcon(file.status)}
                  </span>
                  <span className={styles.path}>{file.path}</span>
                </span>
                <span className={styles.fileMeta}>
                  <span className={styles.statusLabel}>{t(statusKeys[file.status])}</span>
                  <span className={styles.additions}>+{file.additions}</span>
                  <span className={styles.deletions}>−{file.deletions}</span>
                </span>
              </button>

              {isExpanded ? (
                <div className={styles.fileContent} id={`${fileId}-content`}>
                  {file.binary ? (
                    <p className={styles.binary}>
                      <Binary size={15} aria-hidden="true" />
                      {t('agent.diff.binary')}
                    </p>
                  ) : file.patch ? (
                    <DiffPatch patch={file.patch} />
                  ) : (
                    <p className={styles.empty}>{t('agent.diff.empty')}</p>
                  )}
                  {file.truncated ? <p className={styles.truncated}>{t('agent.diff.truncated')}</p> : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
