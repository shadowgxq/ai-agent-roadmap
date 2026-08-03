import { useTranslation } from 'react-i18next';
import { isRouteErrorResponse, useRouteError } from 'react-router-dom';

import { ErrorPage } from '../ErrorPage';

export function RouteErrorPage() {
  const { t } = useTranslation();
  const error = useRouteError();
  const isNotFound = isRouteErrorResponse(error) && error.status === 404;

  return (
    <ErrorPage
      eyebrow={t(isNotFound ? 'errors.notFound.eyebrow' : 'errors.route.eyebrow')}
      title={t(isNotFound ? 'errors.notFound.title' : 'errors.route.title')}
      description={t(isNotFound ? 'errors.notFound.description' : 'errors.route.description')}
      reloadLabel={isNotFound ? undefined : t('errors.actions.reload')}
      homeLabel={t('errors.actions.home')}
    />
  );
}
