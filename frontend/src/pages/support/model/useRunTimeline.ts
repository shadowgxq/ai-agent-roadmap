import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { supportApi } from './support.api';
import { mergeEvents, type TimelineEvent } from './support.types';

export function useRunTimeline(runId: string): {
  events: TimelineEvent[];
  connection: 'connecting' | 'live' | 'reconnecting' | 'done';
} {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [connection, setConnection] = useState<'connecting' | 'live' | 'reconnecting' | 'done'>(
    'connecting',
  );
  useEffect(() => {
    const stream = new EventSource(supportApi.eventsUrl(runId), { withCredentials: true });
    const receive = (message: MessageEvent<string>): void => {
      try {
        const payload: unknown = JSON.parse(message.data);
        if (!payload || typeof payload !== 'object') return;
        const incoming: TimelineEvent = {
          sequence: Number(message.lastEventId),
          kind: message.type,
          payload,
        };
        setEvents((current) => mergeEvents(current, incoming));
        if (message.type === 'status' || message.type === 'done') {
          void queryClient.invalidateQueries({ queryKey: ['support', 'run', runId] });
          void queryClient.invalidateQueries({ queryKey: ['support', 'audit', runId] });
        }
        if (message.type === 'done') {
          stream.close();
          setConnection('done');
        }
      } catch {
        setConnection('reconnecting');
      }
    };
    for (const name of ['status', 'response', 'cancel_requested', 'done'])
      stream.addEventListener(name, receive as EventListener);
    stream.onopen = (): void => setConnection('live');
    stream.onerror = (): void => setConnection('reconnecting');
    return (): void => stream.close();
  }, [runId, queryClient]);
  return { events, connection };
}
