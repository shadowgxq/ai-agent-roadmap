import type { PropsWithChildren } from 'react';
import { act, renderHook } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { i18n } from '../../../shared/i18n';
import { createAgentEventsUrl, createAgentRun, createAgentSession } from './agent.api';
import { useAgentRun } from './useAgentRun';

vi.mock('./agent.api', () => ({
  createAgentEventsUrl: vi.fn(),
  createAgentRun: vi.fn(),
  createAgentSession: vi.fn(),
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly listeners = new Map<string, Set<EventListener>>();
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (typeof listener !== 'function') {
      throw new Error('FakeEventSource only supports function listeners');
    }
    const listeners = this.listeners.get(type) ?? new Set<EventListener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: unknown) {
    const event = new MessageEvent(type, {
      data: JSON.stringify(payload),
    });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

function TestWrapper({ children }: PropsWithChildren) {
  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}

describe('useAgentRun', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
    vi.mocked(createAgentSession).mockResolvedValue({
      sessionId: 'session-1',
    });
    vi.mocked(createAgentRun).mockResolvedValue({
      runId: 'run-1',
      sessionId: 'session-1',
      status: 'queued',
    });
    vi.mocked(createAgentEventsUrl).mockReturnValue('/runs/run-1/events');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('sorts and deduplicates SSE events, then closes on done', async () => {
    const { result } = renderHook(() => useAgentRun(), {
      wrapper: TestWrapper,
    });

    await act(async () => {
      await result.current.startRun('读取 README');
    });

    const source = FakeEventSource.instances[0];
    expect(source.url).toBe('/runs/run-1/events');
    expect(result.current.status).toBe('running');

    await act(async () => {
      source.emit('text', {
        sequence: 2,
        run_id: 'run-1',
        event: 'text',
        data: { turn: 1, text: '完成' },
      });
      source.emit('text', {
        sequence: 0,
        run_id: 'run-1',
        event: 'text',
        data: { turn: 1, text: '开始' },
      });
      source.emit('text', {
        sequence: 0,
        run_id: 'run-1',
        event: 'text',
        data: { turn: 1, text: '重复事件' },
      });
    });

    expect(result.current.events.map((event) => event.sequence)).toEqual([0, 2]);
    expect(result.current.events[0].data).toEqual({ turn: 1, text: '开始' });

    await act(async () => {
      source.emit('done', {
        sequence: 3,
        run_id: 'run-1',
        event: 'done',
        data: { status: 'completed', turn: 1 },
      });
    });

    expect(result.current.status).toBe('completed');
    expect(result.current.isPending).toBe(false);
    expect(source.closed).toBe(true);
  });

  it('turns an SSE connection error into a failed run', async () => {
    const { result } = renderHook(() => useAgentRun(), {
      wrapper: TestWrapper,
    });

    await act(async () => {
      await result.current.startRun('触发连接错误');
    });

    const source = FakeEventSource.instances[0] as FakeEventSource & {
      onerror?: () => void;
    };
    source.onerror?.();

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBeTruthy();
    expect(source.closed).toBe(true);
  });

  it('creates one session and reuses it for subsequent runs', async () => {
    vi.mocked(createAgentRun)
      .mockResolvedValueOnce({
        runId: 'run-1',
        sessionId: 'session-1',
        status: 'queued',
      })
      .mockResolvedValueOnce({
        runId: 'run-2',
        sessionId: 'session-1',
        status: 'queued',
      });

    const { result } = renderHook(() => useAgentRun(), {
      wrapper: TestWrapper,
    });

    await act(async () => {
      await result.current.startRun('第一条消息');
    });
    const firstSource = FakeEventSource.instances[0];

    await act(async () => {
      firstSource.emit('done', {
        sequence: 0,
        run_id: 'run-1',
        event: 'done',
        data: { status: 'completed', turn: 1 },
      });
    });

    await act(async () => {
      await result.current.startRun('第二条消息');
    });

    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(createAgentRun).toHaveBeenNthCalledWith(1, 'session-1', '第一条消息');
    expect(createAgentRun).toHaveBeenNthCalledWith(2, 'session-1', '第二条消息');
    expect(result.current.sessionId).toBe('session-1');
    expect(result.current.runId).toBe('run-2');
  });

  it('clears the session when starting a new run', async () => {
    const { result } = renderHook(() => useAgentRun(), {
      wrapper: TestWrapper,
    });

    await act(async () => {
      await result.current.startRun('当前对话');
    });

    act(() => {
      result.current.resetRun();
    });

    expect(result.current.sessionId).toBeNull();
    expect(result.current.runId).toBeNull();
    expect(result.current.status).toBe('idle');
  });
});
