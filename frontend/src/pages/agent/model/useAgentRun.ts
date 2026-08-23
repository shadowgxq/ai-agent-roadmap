import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { isApiError } from '../../../shared/api';
import {
  createAgentEventsUrl,
  createAgentRun,
  createAgentSession,
  getActiveAgentRun,
} from './agent.api';
import {
  AGENT_EVENT_TYPES,
  parseAgentEvent,
  toRunStatus,
  type ActiveRunConflict,
  type AgentEvent,
  type AgentStoredRun,
  type RunStatus,
} from './agent.types';

type ActiveRunTarget = Pick<AgentStoredRun, 'runId' | 'sessionId' | 'status'> & {
  status: Extract<AgentStoredRun['status'], 'queued' | 'running'>;
};

type AttachRunOptions = {
  phase?: Extract<RunStatus, 'restoring' | 'reconnecting'>;
  preserveEvents?: boolean;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readActiveRunConflict(error: unknown): ActiveRunConflict | null {
  if (!isApiError(error) || error.status !== 409 || !isRecord(error.details)) {
    return null;
  }

  const activeRunId = error.details.active_run_id;
  const sessionId = error.details.session_id;
  const status = error.details.status;
  if (
    typeof activeRunId !== 'string' ||
    typeof sessionId !== 'string' ||
    (status !== 'queued' && status !== 'running')
  ) {
    return null;
  }

  return { activeRunId, sessionId, status };
}

function toActiveRunTarget(run: AgentStoredRun): ActiveRunTarget | null {
  if (run.status !== 'queued' && run.status !== 'running') return null;
  return {
    runId: run.runId,
    sessionId: run.sessionId,
    status: run.status,
  };
}

function toConflict(target: ActiveRunTarget): ActiveRunConflict {
  return {
    activeRunId: target.runId,
    sessionId: target.sessionId,
    status: target.status,
  };
}

function toRunStatusFromStored(status: ActiveRunTarget['status']): RunStatus {
  return status === 'queued' ? 'starting' : 'running';
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
  const [status, setStatus] = useState<RunStatus>('restoring');
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ActiveRunConflict | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const runIdRef = useRef<string | null>(null);
  const isStartingRef = useRef(false);
  const hasFinishedRef = useRef(false);
  const seenSequencesRef = useRef<Set<number>>(new Set());
  const activeLookupVersionRef = useRef(0);

  const closeSource = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const attachRun = useCallback(
    (target: ActiveRunTarget, options: AttachRunOptions = {}) => {
      const { phase, preserveEvents = false } = options;
      if (runIdRef.current === target.runId && sourceRef.current) {
        isStartingRef.current = true;
        setError(null);
        setConflict(null);
        setStatus(toRunStatusFromStored(target.status));
        return;
      }

      closeSource();
      isStartingRef.current = true;
      hasFinishedRef.current = false;
      sessionIdRef.current = target.sessionId;
      runIdRef.current = target.runId;
      setSessionId(target.sessionId);
      setRunId(target.runId);
      setError(null);
      setConflict(null);
      setStatus(phase ?? toRunStatusFromStored(target.status));

      if (!preserveEvents) {
        seenSequencesRef.current = new Set();
        setEvents([]);
      }

      const source = new EventSource(createAgentEventsUrl(target.runId));
      sourceRef.current = source;

      const handleEvent = (rawEvent: Event) => {
        if (sourceRef.current !== source) return;
        const messageEvent = rawEvent as MessageEvent<string>;

        try {
          const event = parseAgentEvent(JSON.parse(messageEvent.data) as unknown);
          if (event.runId !== target.runId || messageEvent.type !== event.type) {
            throw new Error('SSE event envelope does not match the active run');
          }

          if (seenSequencesRef.current.has(event.sequence)) return;
          seenSequencesRef.current.add(event.sequence);
          setEvents((currentEvents) => insertEventInSequence(currentEvents, event));

          if (event.type === 'done') {
            const nextStatus = toRunStatus(event.data.status);
            hasFinishedRef.current = true;
            isStartingRef.current = false;
            setConflict(null);
            setStatus(nextStatus);
            source.close();
            sourceRef.current = null;
            return;
          }

          setStatus((currentStatus) =>
            currentStatus === 'restoring' ||
            currentStatus === 'reconnecting' ||
            currentStatus === 'starting'
              ? 'running'
              : currentStatus,
          );
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
        setStatus('reconnecting');
        source.close();
        sourceRef.current = null;
      };
    },
    [closeSource, t],
  );

  useEffect(() => {
    const lookupVersion = activeLookupVersionRef.current;
    let cancelled = false;

    void getActiveAgentRun()
      .then((activeRun) => {
        if (
          cancelled ||
          lookupVersion !== activeLookupVersionRef.current ||
          isStartingRef.current
        ) {
          return;
        }

        const target = activeRun ? toActiveRunTarget(activeRun) : null;
        if (!target) {
          setStatus('idle');
          return;
        }

        attachRun(target, { phase: 'restoring' });
      })
      .catch(() => {
        if (
          !cancelled &&
          lookupVersion === activeLookupVersionRef.current &&
          !isStartingRef.current
        ) {
          setStatus('idle');
        }
      });

    return () => {
      cancelled = true;
      closeSource();
    };
  }, [attachRun, closeSource]);

  const startRun = useCallback(
    async (task: string) => {
      if (isStartingRef.current) return;

      activeLookupVersionRef.current += 1;
      isStartingRef.current = true;
      closeSource();
      hasFinishedRef.current = false;
      setError(null);
      setConflict(null);
      setStatus('starting');

      try {
        let activeSessionId = sessionIdRef.current;
        if (!activeSessionId) {
          const existingActiveRun = await getActiveAgentRun().catch(() => null);
          const activeTarget = existingActiveRun ? toActiveRunTarget(existingActiveRun) : null;
          if (activeTarget) {
            const activeRunConflict = toConflict(activeTarget);
            attachRun(activeTarget, {
              preserveEvents: runIdRef.current === activeTarget.runId,
            });
            setConflict(activeRunConflict);
            return;
          }

          const createdSession = await createAgentSession();
          activeSessionId = createdSession.sessionId;
          sessionIdRef.current = activeSessionId;
          setSessionId(activeSessionId);
        }

        const createdRun = await createAgentRun(activeSessionId, task);
        attachRun({
          runId: createdRun.runId,
          sessionId: createdRun.sessionId,
          status: 'running',
        });
      } catch (startError) {
        const activeRunConflict = readActiveRunConflict(startError);
        if (activeRunConflict) {
          attachRun(
            {
              runId: activeRunConflict.activeRunId,
              sessionId: activeRunConflict.sessionId,
              status: activeRunConflict.status,
            },
            { preserveEvents: runIdRef.current === activeRunConflict.activeRunId },
          );
          setConflict(activeRunConflict);
          return;
        }

        isStartingRef.current = false;
        setError(getErrorMessage(startError, t('agent.errors.start')));
        setStatus('failed');
      }
    },
    [attachRun, closeSource, t],
  );

  const reconnectActiveRun = useCallback(async () => {
    activeLookupVersionRef.current += 1;
    isStartingRef.current = true;
    setError(null);
    setConflict(null);
    setStatus('reconnecting');

    try {
      const activeRun = await getActiveAgentRun();
      const target = activeRun ? toActiveRunTarget(activeRun) : null;
      if (!target) {
        isStartingRef.current = false;
        setError(t('agent.errors.activeRun'));
        setStatus('failed');
        return;
      }

      attachRun(target, {
        phase: 'reconnecting',
        preserveEvents: runIdRef.current === target.runId,
      });
    } catch (reconnectError) {
      isStartingRef.current = false;
      setError(getErrorMessage(reconnectError, t('agent.errors.activeRun')));
      setStatus('failed');
    }
  }, [attachRun, t]);

  const resetRun = useCallback(() => {
    activeLookupVersionRef.current += 1;
    closeSource();
    isStartingRef.current = false;
    sessionIdRef.current = null;
    runIdRef.current = null;
    hasFinishedRef.current = false;
    seenSequencesRef.current = new Set();
    setEvents([]);
    setSessionId(null);
    setRunId(null);
    setError(null);
    setConflict(null);
    setStatus('idle');
  }, [closeSource]);

  const resumeSession = useCallback(
    (nextSessionId: string) => {
      if (isStartingRef.current) return;

      activeLookupVersionRef.current += 1;
      closeSource();
      isStartingRef.current = false;
      sessionIdRef.current = nextSessionId;
      runIdRef.current = null;
      hasFinishedRef.current = false;
      seenSequencesRef.current = new Set();
      setEvents([]);
      setSessionId(nextSessionId);
      setRunId(null);
      setError(null);
      setConflict(null);
      setStatus('idle');
    },
    [closeSource],
  );

  return {
    canReconnect: Boolean(conflict) || status === 'reconnecting',
    conflict,
    error,
    events,
    isPending:
      status === 'restoring' ||
      status === 'starting' ||
      status === 'running' ||
      status === 'reconnecting',
    reconnectActiveRun,
    resetRun,
    resumeSession,
    runId,
    sessionId,
    startRun,
    status,
  };
}
