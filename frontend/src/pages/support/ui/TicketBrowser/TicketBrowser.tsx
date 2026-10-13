import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { supportApi } from '../../model/support.api';
import type { SessionDto } from '../../model/support.types';
import { SupportButton } from '../Controls';
import { RunWorkspace } from '../RunWorkspace';
import { TicketComposer } from '../TicketComposer';
import styles from '../../SupportPage.module.css';

export function TicketBrowser({ session }: { session: SessionDto }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const tickets = useQuery({
    queryKey: ['support', 'tickets'],
    queryFn: supportApi.tickets,
    enabled: !!session,
  });
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedTicket = tickets.data?.find((ticket) => ticket.ticket_id === selectedTicketId);
  const runs = useQuery({
    queryKey: ['support', 'runs', selectedTicketId],
    queryFn: () => supportApi.runs(selectedTicketId ?? ''),
    enabled: !!session && !!selectedTicketId,
    refetchInterval: 5000,
  });
  const effectiveRunId = selectedRunId ?? runs.data?.[0]?.run_id;
  const submissionKey = useRef<{ ticketId: string; key: string } | null>(null);
  const start = useMutation({
    mutationFn: () => {
      if (!selectedTicketId || !session) throw new Error('No ticket selected');
      if (!submissionKey.current || submissionKey.current.ticketId !== selectedTicketId)
        submissionKey.current = { ticketId: selectedTicketId, key: crypto.randomUUID() };
      return supportApi.start(selectedTicketId, session.csrf_token, submissionKey.current.key);
    },
    onSuccess: (run) => {
      setSelectedRunId(run.run_id);
      submissionKey.current = null;
      void queryClient.invalidateQueries({ queryKey: ['support', 'runs'] });
    },
  });
  const canOperate = session?.identity.role === 'operator' || session?.identity.role === 'admin';
  const selectTicket = (ticketId: string): void => {
    if (start.isPending) return;
    setSelectedTicketId(ticketId);
    setSelectedRunId(null);
    start.reset();
  };
  return (
    <div className={styles.layout}>
      <aside>
        {canOperate ? <TicketComposer csrf={session.csrf_token} onCreated={selectTicket} /> : null}
        <section className={styles.panel}>
          <h2>{t('support.tickets')}</h2>
          {tickets.isPending ? (
            <p>{t('support.loading')}</p>
          ) : tickets.isError ? (
            <p role="alert">
              {t('support.actionError')}
              <SupportButton onClick={() => void tickets.refetch()}>
                {t('support.retry')}
              </SupportButton>
            </p>
          ) : tickets.data?.length ? (
            <ul className={styles.list}>
              {tickets.data.map((ticket) => (
                <li key={ticket.ticket_id}>
                  <SupportButton
                    disabled={start.isPending}
                    aria-pressed={ticket.ticket_id === selectedTicketId}
                    onClick={() => selectTicket(ticket.ticket_id)}
                  >
                    {ticket.subject}
                  </SupportButton>
                </li>
              ))}
            </ul>
          ) : (
            <p>{t('support.empty')}</p>
          )}
        </section>
      </aside>
      <section>
        {selectedTicket ? (
          <section className={styles.panel}>
            <h2>{selectedTicket.subject}</h2>
            <p className={styles.response}>{selectedTicket.description}</p>
            {canOperate ? (
              <SupportButton
                disabled={
                  start.isPending ||
                  runs.data?.some((run) =>
                    ['queued', 'running', 'waiting_approval'].includes(run.status),
                  )
                }
                onClick={() => start.mutate()}
              >
                {t(start.isPending ? 'support.pending' : 'support.start')}
              </SupportButton>
            ) : null}
            {start.isError ? <p role="alert">{t('support.actionError')}</p> : null}
            <div className={styles.row}>
              {runs.data?.map((run) => (
                <SupportButton
                  key={run.run_id}
                  aria-pressed={run.run_id === effectiveRunId}
                  onClick={() => setSelectedRunId(run.run_id)}
                >
                  {t(`support.status.${run.status}`)} · {run.run_id.slice(0, 8)}
                </SupportButton>
              ))}
            </div>
            {runs.isError ? <p role="alert">{t('support.actionError')}</p> : null}
          </section>
        ) : (
          <section className={styles.panel}>
            <p>{t('support.selectTicket')}</p>
          </section>
        )}
        {effectiveRunId ? (
          <RunWorkspace key={effectiveRunId} runId={effectiveRunId} session={session} />
        ) : null}
      </section>
    </div>
  );
}
