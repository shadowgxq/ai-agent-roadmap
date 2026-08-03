import { useTranslation } from 'react-i18next';

import { ErrorPage } from '../ErrorPage';

export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <ErrorPage
      eyebrow={t('errors.notFound.eyebrow')}
      title={t('errors.notFound.title')}
      description={t('errors.notFound.description')}
      homeLabel={t('errors.actions.home')}
    />
  );
}
