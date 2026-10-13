import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { supportApi } from '../../model/support.api';
import { SupportButton, SupportInput } from '../Controls';
import styles from '../../SupportPage.module.css';

export function LoginPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const login = useMutation({
    mutationFn: () => supportApi.login(username, password),
    onSuccess: (session) => {
      queryClient.setQueryData(['support', 'session'], session);
      setPassword('');
    },
  });
  return (
    <form
      className={styles.panel}
      onSubmit={(event) => {
        event.preventDefault();
        if (!login.isPending) login.mutate();
      }}
      aria-busy={login.isPending}
    >
      <h2>{t('support.login')}</h2>
      <label>
        {t('support.username')}
        <SupportInput
          required
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
      </label>
      <label>
        {t('support.password')}
        <SupportInput
          required
          minLength={8}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {login.isError ? <p role="alert">{t('support.loginError')}</p> : null}
      <SupportButton type="submit" disabled={login.isPending}>
        {t(login.isPending ? 'support.pending' : 'support.login')}
      </SupportButton>
    </form>
  );
}
