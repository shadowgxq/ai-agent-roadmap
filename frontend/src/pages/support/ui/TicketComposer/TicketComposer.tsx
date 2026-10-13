import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { supportApi } from '../../model/support.api';
import { SupportButton, SupportInput, SupportTextarea } from '../Controls';
import styles from '../../SupportPage.module.css';

type Props = { csrf: string; onCreated: (ticketId: string) => void };
export function TicketComposer({ csrf, onCreated }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [kb, setKb] = useState('');
  const create = useMutation({
    mutationFn: () =>
      supportApi.createTicket({ subject, description, knowledge_base_id: kb }, csrf),
    onSuccess: (ticket) => {
      void queryClient.invalidateQueries({ queryKey: ['support', 'tickets'] });
      onCreated(ticket.ticket_id);
      setSubject('');
      setDescription('');
    },
  });
  return (
    <form
      className={styles.panel}
      aria-busy={create.isPending}
      onSubmit={(event) => {
        event.preventDefault();
        if (!create.isPending) create.mutate();
      }}
    >
      <h2>{t('support.newTicket')}</h2>
      <label>
        {t('support.knowledgeBase')}
        <SupportInput required value={kb} onChange={(event) => setKb(event.target.value)} />
      </label>
      <label>
        {t('support.subject')}
        <SupportInput
          required
          maxLength={200}
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
        />
      </label>
      <label>
        {t('support.description')}
        <SupportTextarea
          required
          maxLength={20000}
          rows={4}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      {create.isError ? <p role="alert">{t('support.actionError')}</p> : null}
      <SupportButton type="submit" disabled={create.isPending}>
        {t(create.isPending ? 'support.pending' : 'support.create')}
      </SupportButton>
    </form>
  );
}
