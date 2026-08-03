import { House, RefreshCw } from '../../../shared/icons';
import styles from './ErrorPage.module.css';

export type ErrorPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  reloadLabel?: string;
  homeLabel: string;
};

function reloadPage() {
  window.location.reload();
}

export function ErrorPage({ eyebrow, title, description, reloadLabel, homeLabel }: ErrorPageProps) {
  return (
    <main className={styles.root} aria-labelledby="app-error-title">
      <div className={styles.content} role="alert">
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h1 id="app-error-title" className={styles.title}>
          {title}
        </h1>
        <p className={styles.description}>{description}</p>

        <div className={styles.actions}>
          {reloadLabel ? (
            <button className={styles.primaryAction} type="button" onClick={reloadPage}>
              <RefreshCw size={18} aria-hidden="true" />
              {reloadLabel}
            </button>
          ) : null}
          <a className={styles.secondaryAction} href="/">
            <House size={18} aria-hidden="true" />
            {homeLabel}
          </a>
        </div>
      </div>
    </main>
  );
}
