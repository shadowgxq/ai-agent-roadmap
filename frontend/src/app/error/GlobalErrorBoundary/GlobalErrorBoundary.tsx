import { Component, type ErrorInfo, type PropsWithChildren } from 'react';

import { i18n } from '../../../shared/i18n';
import { ErrorPage } from '../ErrorPage';

export type GlobalErrorBoundaryProps = PropsWithChildren<{
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}>;

type GlobalErrorBoundaryState = {
  hasError: boolean;
};

export class GlobalErrorBoundary extends Component<
  GlobalErrorBoundaryProps,
  GlobalErrorBoundaryState
> {
  state: GlobalErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): GlobalErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
      return;
    }

    console.error('Uncaught application error', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <ErrorPage
          eyebrow={i18n.t('errors.global.eyebrow')}
          title={i18n.t('errors.global.title')}
          description={i18n.t('errors.global.description')}
          reloadLabel={i18n.t('errors.actions.reload')}
          homeLabel={i18n.t('errors.actions.home')}
        />
      );
    }

    return this.props.children;
  }
}
