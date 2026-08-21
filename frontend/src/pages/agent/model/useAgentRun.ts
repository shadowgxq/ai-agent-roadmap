import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { createAgentEventsUrl, createAgentRun, createAgentSession } from './agent.api';
import {
  AGENT_EVENT_TYPES,
  parseAgentEvent,
  toRunStatus,
  type AgentEvent,
  type RunStatus,
} from './agent.types';

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function insertEventInSequence(currentEvents: AgentEvent[], event: AgentEvent) {
  const lastEvent = currentEvents[currentEvents.length - 1];
  if (!lastEvent || lastEvent.sequence < event.sequence) {
    return [...currentEvents, event];
  }

  const nextEvents = [...currentEvents, event];
  nextEvents.sort((left, right) => left.sequence - right.sequence);
  return nextEvents;
}

export function useAgentRun() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const isStartingRef = useRef(false);
  const hasFinishedRef = useRef(false);
  const seenSequencesRef = useRef<Set<number>>(new Set());

  const closeSource = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  useEffect(() => closeSource, [closeSource]);

  const startRun = useCallback(
    async (task: string) => {
      if (isStartingRef.current) return;

      isStartingRef.current = true;
      closeSource();
      hasFinishedRef.current = false;
      seenSequencesRef.current = new Set();
      setEvents([]);
      setRunId(null);
      setError(null);
      setStatus('starting');

      try {
        let activeSessionId = sessionIdRef.current;
        if (!activeSessionId) {
          const createdSession = await createAgentSession();
          activeSessionId = createdSession.sessionId;
          sessionIdRef.current = activeSessionId;
          setSessionId(activeSessionId);
        }

        const createdRun = await createAgentRun(activeSessionId, task);
        sessionIdRef.current = createdRun.sessionId;
        setSessionId(createdRun.sessionId);
        setRunId(createdRun.runId);
        setStatus('running');

        const source = new EventSource(createAgentEventsUrl(createdRun.runId));
        sourceRef.current = source;

        const handleEvent = (rawEvent: Event) => {
          if (sourceRef.current !== source) return;
          const messageEvent = rawEvent as MessageEvent<string>;

          try {
            const event = parseAgentEvent(JSON.parse(messageEvent.data) as unknown);
            if (event.runId !== createdRun.runId || messageEvent.type !== event.type) {
              throw new Error('SSE event envelope does not match the active run');
            }

            if (seenSequencesRef.current.has(event.sequence)) return;
            seenSequencesRef.current.add(event.sequence);
            setEvents((currentEvents) => insertEventInSequence(currentEvents, event));

            if (event.type === 'done') {
              const nextStatus = toRunStatus(event.data.status);
              hasFinishedRef.current = true;
              isStartingRef.current = false;
              setStatus(nextStatus);
              source.close();
              sourceRef.current = null;
            }
          } catch {
            isStartingRef.current = false;
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
          isStartingRef.current = false;
          setError(t('agent.errors.stream'));
          setStatus('failed');
          source.close();
          sourceRef.current = null;
        };
      } catch (startError) {
        isStartingRef.current = false;
        setError(getErrorMessage(startError, t('agent.errors.start')));
        setStatus('failed');
      }
    },
    [closeSource, t],
  );

  const resetRun = useCallback(() => {
    closeSource();
    isStartingRef.current = false;
    sessionIdRef.current = null;
    hasFinishedRef.current = false;
    seenSequencesRef.current = new Set();
    setEvents([]);
    setSessionId(null);
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
    sessionId,
    startRun,
    status,
  };
}
