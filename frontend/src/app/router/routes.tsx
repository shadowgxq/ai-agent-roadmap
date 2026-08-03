import type { RouteObject } from 'react-router-dom';

import { AgentPage } from '../../pages/agent';
import { NotFoundPage } from '../error/NotFoundPage';
import { RouteErrorPage } from '../error/RouteErrorPage';

export const appRoutes: RouteObject[] = [
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
