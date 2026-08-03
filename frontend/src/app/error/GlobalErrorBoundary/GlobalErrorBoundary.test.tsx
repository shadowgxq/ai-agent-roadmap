import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { i18n } from '../../../shared/i18n';
import { GlobalErrorBoundary } from './GlobalErrorBoundary';

function BrokenChild(): never {
  throw new Error('render failed');
}

describe('GlobalErrorBoundary', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders its children when no error is thrown', () => {
    render(
      <GlobalErrorBoundary>
        <p>Application content</p>
      </GlobalErrorBoundary>,
    );

    expect(screen.getByText('Application content')).toBeInTheDocument();
  });

  it('renders a recoverable fallback and reports render errors', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const handleError = vi.fn();

    render(
      <GlobalErrorBoundary onError={handleError}>
        <BrokenChild />
      </GlobalErrorBoundary>,
    );

    expect(
      screen.getByRole('heading', { name: 'The application hit an unexpected error.' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Return home' })).toHaveAttribute('href', '/');
    expect(handleError).toHaveBeenCalledOnce();
  });
});
