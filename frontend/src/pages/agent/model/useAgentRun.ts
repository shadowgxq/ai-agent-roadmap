import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { createAgentEventsUrl, createAgentRun } from './agent.api';
import {
  AGENT_EVENT_TYPES,
  toAgentEvent,
  toRunStatus,
  type AgentEvent,
  type AgentEventDto,
  type RunStatus,
} from './agent.types';

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useAgentRun() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const hasFinishedRef = useRef(false);

  const closeSource = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  useEffect(() => closeSource, [closeSource]);

  const startRun = useCallback(
    async (task: string) => {
      closeSource();
      hasFinishedRef.current = false;
      setEvents([]);
      setRunId(null);
      setError(null);
      setStatus('starting');

      try {
        const createdRun = await createAgentRun(task);
        setRunId(createdRun.runId);
        setStatus('running');

        const source = new EventSource(createAgentEventsUrl(createdRun.runId));
        sourceRef.current = source;

        const handleEvent = (rawEvent: Event) => {
          const messageEvent = rawEvent as MessageEvent<string>;

          try {
            const eventDto = JSON.parse(messageEvent.data) as AgentEventDto;
            const event = toAgentEvent(eventDto);
            setEvents((currentEvents) => [...currentEvents, event]);

            if (event.type === 'done') {
              const nextStatus = toRunStatus(String(event.data.status ?? 'completed'));
              hasFinishedRef.current = true;
              setStatus(nextStatus);
              source.close();
              sourceRef.current = null;
            }
          } catch {
            setError(t('agent.errors.event'));
            setStatus('failed');
            source.close();
            sourceRef.current = null;
          }
        };

        AGENT_EVENT_TYPES.forEach((eventType) => {
          source.addEventListener(eventType, handleEvent);
        });

        source.onerror = () => {
          if (hasFinishedRef.current) return;
          setError(t('agent.errors.stream'));
          setStatus('failed');
          source.close();
          sourceRef.current = null;
        };
      } catch (startError) {
        setError(getErrorMessage(startError, t('agent.errors.start')));
        setStatus('failed');
      }
    },
    [closeSource, t],
  );

  const resetRun = useCallback(() => {
    closeSource();
    hasFinishedRef.current = false;
    setEvents([]);
    setRunId(null);
    setError(null);
    setStatus('idle');
  }, [closeSource]);

  return {
    error,
    events,
    isPending: status === 'starting' || status === 'running',
    resetRun,
    runId,
    startRun,
    status,
  };
}
