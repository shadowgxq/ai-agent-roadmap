import { GlobalErrorBoundary } from './error/GlobalErrorBoundary';
import { AppProviders } from './providers/AppProviders';
import { AppRouter } from './router/AppRouter';

export function App() {
  return (
    <GlobalErrorBoundary>
      <AppProviders>
        <AppRouter />
      </AppProviders>
    </GlobalErrorBoundary>
  );
}
