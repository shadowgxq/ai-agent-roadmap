import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { supportApi } from './support.api';
import { decodeTimelineEvent, mergeEvents, type TimelineEvent } from './support.types';

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
    let isClosed = false;
    const receive = (message: MessageEvent<string>): void => {
      try {
        if (isClosed) return;
        const incoming = decodeTimelineEvent(
          Number(message.lastEventId),
          message.type,
          message.data,
        );
        if (!incoming) return;
        setEvents((current) => mergeEvents(current, incoming));
        if (message.type === 'status' || message.type === 'done') {
          void queryClient.invalidateQueries({ queryKey: ['support', 'run', runId] });
          void queryClient.invalidateQueries({ queryKey: ['support', 'audit', runId] });
        }
        if (message.type === 'done') {
          isClosed = true;
          stream.close();
          setConnection('done');
        }
      } catch {
        setConnection('reconnecting');
      }
    };
    for (const name of ['status', 'response', 'cancel_requested', 'done'])
      stream.addEventListener(name, receive as EventListener);
    stream.onopen = (): void => {
      if (!isClosed) setConnection('live');
    };
    stream.onerror = (): void => {
      if (!isClosed) setConnection('reconnecting');
    };
    return (): void => {
      isClosed = true;
      stream.close();
    };
  }, [runId, queryClient]);
  return { events, connection };
}
