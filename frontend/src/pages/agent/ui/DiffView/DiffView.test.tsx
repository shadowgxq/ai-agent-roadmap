import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { i18n } from '../../../../shared/i18n';
import type { DiffFileItem } from '../../model';
import { DiffView } from './DiffView';

const modifiedFile: DiffFileItem = {
  path: 'src/main.py',
  status: 'modified',
  patch: '--- a/src/main.py\n+++ b/src/main.py\n-old\n+new',
  additions: 1,
  deletions: 1,
  binary: false,
  truncated: false,
};

describe('DiffView', () => {
  afterEach(() => cleanup());

  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('shows changed files and supports keyboard-friendly disclosure', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <DiffView files={[modifiedFile]} />
      </I18nextProvider>,
    );

    expect(screen.getByRole('navigation', { name: 'Changed files' })).toBeInTheDocument();
    expect(screen.getAllByText('src/main.py')).toHaveLength(2);
    expect(screen.getByText('+new')).toBeInTheDocument();

    const header = screen.getByRole('button', { name: /src\/main\.py.*Modified/ });
    expect(header).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(header);

    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('+new')).not.toBeInTheDocument();
  });
});
