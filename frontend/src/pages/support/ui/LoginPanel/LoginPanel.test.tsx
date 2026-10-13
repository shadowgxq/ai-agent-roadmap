import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { supportApi } from '../../model/support.api';
import { LoginPanel } from './LoginPanel';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(() => vi.restoreAllMocks());

it('drops previous tenant cache after successful sign-in', async () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(['support', 'tickets'], [{ ticket_id: 'private-old-tenant' }]);
  vi.spyOn(supportApi, 'login').mockResolvedValue({
    identity: { organization_id: 'new-tenant', user_id: 'user', role: 'operator' },
    csrf_token: 'csrf',
  });
  render(
    <QueryClientProvider client={queryClient}>
      <LoginPanel />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('support.username'), 'user');
  await user.type(screen.getByLabelText('support.password'), 'test-password');
  await user.click(screen.getByRole('button', { name: 'support.login' }));
  await waitFor(() => expect(queryClient.getQueryData(['support', 'session'])).toBeDefined());
  expect(queryClient.getQueryData(['support', 'tickets'])).toBeUndefined();
});
