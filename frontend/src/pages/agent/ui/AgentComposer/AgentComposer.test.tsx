import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { i18n } from '../../../../shared/i18n';
import { AgentComposer } from './AgentComposer';

function renderComposer(overrides: Partial<ComponentProps<typeof AgentComposer>> = {}) {
  const props: ComponentProps<typeof AgentComposer> = {
    hasSession: false,
    isPending: false,
    onReset: vi.fn(),
    onSubmit: vi.fn(),
    onTaskChange: vi.fn(),
    task: '检查项目',
    ...overrides,
  };

  render(
    <I18nextProvider i18n={i18n}>
      <AgentComposer {...props} />
    </I18nextProvider>,
  );

  return props;
}

describe('AgentComposer', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('submits with Enter but keeps Shift+Enter for a newline', () => {
    const props = renderComposer();
    const textarea = screen.getByLabelText('Task');

    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: true });

    expect(props.onSubmit).toHaveBeenCalledOnce();
  });

  it('does not submit while an active run is pending', () => {
    const props = renderComposer({ isPending: true });
    const textarea = screen.getByLabelText('Task');

    expect(textarea).toBeDisabled();
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });

    expect(props.onSubmit).not.toHaveBeenCalled();
  });
});
