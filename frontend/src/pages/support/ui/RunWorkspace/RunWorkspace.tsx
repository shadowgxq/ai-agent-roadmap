import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { supportApi } from '../../model/support.api';
import type { Decision, SessionDto } from '../../model/support.types';
import { useRunTimeline } from '../../model/useRunTimeline';
import { SupportButton, SupportTextarea } from '../Controls';
import styles from '../../SupportPage.module.css';

type Props = { runId: string; session: SessionDto };
export function RunWorkspace({ runId, session }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const runQuery = useQuery({
    queryKey: ['support', 'run', runId],
    queryFn: () => supportApi.run(runId),
  });
  const auditQuery = useQuery({
    queryKey: ['support', 'audit', runId],
    queryFn: () => supportApi.audit(runId),
  });
  const { events, connection } = useRunTimeline(runId);
  const [feedback, setFeedback] = useState('');
  const run = runQuery.data;
  const approval = useMutation({
    mutationFn: (decision: Decision) =>
      supportApi.approve(
        runId,
        decision,
        run?.projection.proposal_hash ?? '',
        feedback,
        session.csrf_token,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['support'] });
      setFeedback('');
    },
  });
  const cancel = useMutation({
    mutationFn: () => supportApi.cancel(runId, session.csrf_token),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['support', 'run', runId] });
    },
  });
  const canApprove = session.identity.role === 'approver' || session.identity.role === 'admin';
  const canOperate = session.identity.role === 'operator' || session.identity.role === 'admin';
  const isActive = run && ['queued', 'running', 'waiting_approval'].includes(run.status);
  const projection = run?.projection;
  return (
    <div className={styles.detail}>
      <section className={styles.panel}>
        <div className={styles.row}>
          <h2>{t('support.run')}</h2>
          <span className={styles.badge}>{t(`support.status.${run?.status ?? 'unknown'}`)}</span>
        </div>
        <p className={styles.muted}>{runId}</p>
        {runQuery.isPending ? <p role="status">{t('support.loading')}</p> : null}
        {runQuery.isError ? (
          <p role="alert">
            {t('support.actionError')}{' '}
            <SupportButton onClick={() => void runQuery.refetch()}>
              {t('support.retry')}
            </SupportButton>
          </p>
        ) : null}
        {canOperate && isActive ? (
          <SupportButton
            disabled={cancel.isPending || run.cancel_requested}
            onClick={() => cancel.mutate()}
          >
            {t(run.cancel_requested ? 'support.cancelRequested' : 'support.cancel')}
          </SupportButton>
        ) : null}
        {cancel.isError ? <p role="alert">{t('support.actionError')}</p> : null}
        {projection?.draft_response ? (
          <p className={styles.response}>{projection.draft_response}</p>
        ) : null}
        {projection?.error_code ? <p role="alert">{projection.error_code}</p> : null}
        <h3>{t('support.citations')}</h3>
        {projection?.evidence_refs?.length ? (
          projection.evidence_refs.map((evidence) => (
            <details key={evidence.chunk_id ?? evidence.source_id}>
              <summary>
                {evidence.document_title ?? evidence.title} · v{evidence.document_version ?? 1}
              </summary>
              <p>
                {evidence.heading_path?.join(' / ')}{' '}
                {evidence.page ? `${t('support.page')} ${evidence.page}` : ''}
              </p>
              <p>{evidence.snippet}</p>
              <code>{evidence.chunk_id ?? evidence.source_id}</code>
            </details>
          ))
        ) : (
          <p className={styles.muted}>{t('support.noEvidence')}</p>
        )}
      </section>
      {run?.status === 'waiting_approval' ? (
        <section className={styles.panel} aria-busy={approval.isPending}>
          <h2>{t('support.approval')}</h2>
          {canApprove ? (
            <>
              <label>
                {t('support.feedback')}
                <SupportTextarea
                  rows={3}
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                />
              </label>
              <div className={styles.row}>
                {(['approve', 'reject', 'revise'] as const).map((decision) => (
                  <SupportButton
                    key={decision}
                    disabled={
                      approval.isPending ||
                      !projection?.proposal_hash ||
                      (decision !== 'approve' && !feedback.trim())
                    }
                    onClick={() => approval.mutate(decision)}
                  >
                    {t(`support.${decision}`)}
                  </SupportButton>
                ))}
              </div>
            </>
          ) : (
            <p>{t('support.approverOnly')}</p>
          )}
          {approval.isError ? <p role="alert">{t('support.actionError')}</p> : null}
        </section>
      ) : null}
      <section className={styles.panel}>
        <div className={styles.row}>
          <h2>{t('support.timeline')}</h2>
          <span>{t(`support.connection.${connection}`)}</span>
        </div>
        <ol className={styles.timeline}>
          {events.map((event) => (
            <li key={event.sequence}>
              <span className={styles.muted}>#{event.sequence}</span>{' '}
              <strong>{t(`support.event.${event.kind}`, { defaultValue: event.kind })}</strong>
              {event.payload.status ? (
                <span> · {t(`support.status.${event.payload.status}`)}</span>
              ) : null}
              {event.payload.draft_response ? <p>{event.payload.draft_response}</p> : null}
            </li>
          ))}
        </ol>
      </section>
      <section className={styles.panel}>
        <h2>{t('support.audit')}</h2>
        {auditQuery.isError ? (
          <p role="alert">{t('support.actionError')}</p>
        ) : (
          <ul className={styles.timeline}>
            {auditQuery.data?.map((entry, index) => (
              <li key={`${entry.created_at}-${index}`}>
                <strong>{entry.action}</strong> · {entry.actor_id}
                <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
