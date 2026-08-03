import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { i18n } from '../../shared/i18n';
import { RouteErrorPage } from '../error/RouteErrorPage';
import { appRoutes } from './routes';

function BrokenRoute(): never {
  throw new Error('route render failed');
}

function renderRouter(router: ReturnType<typeof createMemoryRouter>) {
  return render(
    <I18nextProvider i18n={i18n}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </I18nextProvider>,
  );
}

describe('AppRouter', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('renders the not-found page for an unknown path', () => {
    const router = createMemoryRouter(appRoutes, { initialEntries: ['/missing'] });

    renderRouter(router);

    expect(screen.getByRole('heading', { name: 'This page does not exist.' })).toBeInTheDocument();
  });

  it('renders the route error page when a route fails to render', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const router = createMemoryRouter(
      [
        {
          path: '/',
          element: <BrokenRoute />,
          errorElement: <RouteErrorPage />,
        },
      ],
      { initialEntries: ['/'] },
    );

    renderRouter(router);

    expect(
      screen.getByRole('heading', { name: 'This page could not be displayed.' }),
    ).toBeInTheDocument();
  });
});
