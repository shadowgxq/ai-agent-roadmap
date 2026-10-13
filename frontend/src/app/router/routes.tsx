import type { RouteObject } from 'react-router-dom';

import { AgentPage } from '../../pages/agent';
import { SupportPage } from '../../pages/support';
import { NotFoundPage } from '../error/NotFoundPage';
import { RouteErrorPage } from '../error/RouteErrorPage';

export const appRoutes: RouteObject[] = [
  { path: '/support', element: <SupportPage />, errorElement: <RouteErrorPage /> },
  {
    path: '/',
    element: <AgentPage />,
    errorElement: <RouteErrorPage />,
  },
  {
    path: '/agent',
    element: <AgentPage />,
    errorElement: <RouteErrorPage />,
  },
  {
    path: '*',
    element: <NotFoundPage />,
  },
];
