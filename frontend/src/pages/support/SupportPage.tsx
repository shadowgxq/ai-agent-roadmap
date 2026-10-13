import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { supportApi, SupportApiError } from './model/support.api';
import { SupportButton } from './ui/Controls';
import { LoginPanel } from './ui/LoginPanel';
import { TicketBrowser } from './ui/TicketBrowser';
import styles from './SupportPage.module.css';

export function SupportPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ['support', 'session'],
    queryFn: supportApi.session,
    retry: false,
  });
  const logout = useMutation({
    mutationFn: () => supportApi.logout(session.data?.csrf_token ?? ''),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['support'] });
      queryClient.setQueryData(['support', 'session'], null);
    },
  });
  const isUnavailable =
    session.isError && !(session.error instanceof SupportApiError && session.error.status === 403);
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t('support.eyebrow')}</p>
          <h1>{t('support.title')}</h1>
          <p>{t('support.subtitle')}</p>
        </div>
        {session.data ? (
          <div>
            <p>
              {session.data.identity.user_id} · {session.data.identity.role}
            </p>
            <SupportButton disabled={logout.isPending} onClick={() => logout.mutate()}>
              {t('support.logout')}
            </SupportButton>
          </div>
        ) : null}
      </header>
      {logout.isError ? <p role="alert">{t('support.actionError')}</p> : null}
      {session.isPending ? (
        <p role="status">{t('support.loading')}</p>
      ) : isUnavailable ? (
        <section className={styles.panel}>
          <p role="alert">{t('support.actionError')}</p>
          <SupportButton onClick={() => void session.refetch()}>{t('support.retry')}</SupportButton>
        </section>
      ) : session.data ? (
        <TicketBrowser
          key={`${session.data.identity.organization_id}:${session.data.identity.user_id}`}
          session={session.data}
        />
      ) : (
        <LoginPanel />
      )}
    </main>
  );
}
