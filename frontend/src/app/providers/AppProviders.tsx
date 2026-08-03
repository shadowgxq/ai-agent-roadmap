import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PropsWithChildren } from 'react';
import { I18nextProvider } from 'react-i18next';

import { i18n } from '../../shared/i18n';
import { ThemeInitializer } from './ThemeInitializer';

const queryClient = new QueryClient();

export function AppProviders({ children }: PropsWithChildren) {
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <ThemeInitializer />
        {children}
      </QueryClientProvider>
    </I18nextProvider>
  );
}
