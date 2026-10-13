import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useRunTimeline } from './useRunTimeline';

class StreamDouble {
  static latest: StreamDouble;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  isClosed = false;
  listeners = new Map<string, EventListener>();
  constructor(public url: string) {
    StreamDouble.latest = this;
  }
  addEventListener(name: string, callback: EventListener): void {
    this.listeners.set(name, callback);
  }
  close(): void {
    this.isClosed = true;
  }
  emit(kind: string, sequence: number): void {
    this.listeners.get(kind)?.(
      new MessageEvent(kind, {
        lastEventId: String(sequence),
        data: JSON.stringify({ status: kind === 'done' ? 'succeeded' : 'running' }),
      }),
    );
  }
}

afterEach(() => vi.unstubAllGlobals());

describe('support SSE lifecycle', () => {
  it('reconnects the same run, deduplicates replay, and closes only on done or unmount', () => {
    vi.stubGlobal('EventSource', StreamDouble);
    const queryClient = new QueryClient();
    function Wrapper({ children }: PropsWithChildren) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }
    const { result, unmount } = renderHook(() => useRunTimeline('run-1'), { wrapper: Wrapper });
    const stream = StreamDouble.latest;
    expect(stream.url).toContain('/runs/run-1/events');
    act(() => {
      stream.emit('status', 1);
      stream.onerror?.();
    });
    expect(result.current.connection).toBe('reconnecting');
    expect(stream.isClosed).toBe(false);
    act(() => {
      stream.onopen?.();
      stream.emit('status', 1);
      stream.emit('done', 2);
    });
    expect(result.current.events.map((event) => event.sequence)).toEqual([1, 2]);
    expect(result.current.connection).toBe('done');
    expect(stream.isClosed).toBe(true);
    unmount();
  });
});
