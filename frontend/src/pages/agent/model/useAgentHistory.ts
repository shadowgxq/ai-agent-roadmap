import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { getAgentSessionDetail, listAgentSessions } from './agent.api';
import type { AgentSession, AgentSessionDetail } from './agent.types';

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function useAgentHistory() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentSessionDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedSessionIdRef = useRef<string | null>(null);
  const requestVersionRef = useRef(0);

  const loadHistory = useCallback(
    async (preferredSessionId?: string) => {
      const requestVersion = requestVersionRef.current + 1;
      requestVersionRef.current = requestVersion;
      setIsLoading(true);
      setError(null);

      try {
        const nextSessions = await listAgentSessions();
        if (requestVersion !== requestVersionRef.current) return;
        setSessions(nextSessions);

        const nextSessionId =
          preferredSessionId ??
          selectedSessionIdRef.current ??
          nextSessions[0]?.sessionId ??
          null;
        if (!nextSessionId) {
          selectedSessionIdRef.current = null;
          setSelectedSessionId(null);
          setDetail(null);
          return;
        }

        const nextDetail = await getAgentSessionDetail(nextSessionId);
        if (requestVersion !== requestVersionRef.current) return;
        selectedSessionIdRef.current = nextSessionId;
        setSelectedSessionId(nextSessionId);
        setDetail(nextDetail);
      } catch (historyError) {
        if (requestVersion !== requestVersionRef.current) return;
        setError(getErrorMessage(historyError, t('agent.errors.history')));
      } finally {
        if (requestVersion === requestVersionRef.current) {
          setIsLoading(false);
        }
      }
    },
    [t],
  );

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void loadHistory();
    });

    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  const selectSession = useCallback(
    (nextSessionId: string) => {
      const requestVersion = requestVersionRef.current + 1;
      requestVersionRef.current = requestVersion;
      selectedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
      setIsLoading(true);
      setError(null);

      void getAgentSessionDetail(nextSessionId)
        .then((nextDetail) => {
          if (requestVersion !== requestVersionRef.current) return;
          setDetail(nextDetail);
        })
        .catch((historyError: unknown) => {
          if (requestVersion !== requestVersionRef.current) return;
          setError(getErrorMessage(historyError, t('agent.errors.history')));
        })
        .finally(() => {
          if (requestVersion === requestVersionRef.current) {
            setIsLoading(false);
          }
        });
    },
    [t],
  );

  const refreshDetail = useCallback(
    async (sessionId: string) => {
      try {
        const nextDetail = await getAgentSessionDetail(sessionId);
        if (selectedSessionIdRef.current !== sessionId) return;
        setDetail(nextDetail);
      } catch (historyError: unknown) {
        if (selectedSessionIdRef.current !== sessionId) return;
        setError(getErrorMessage(historyError, t('agent.errors.history')));
      }
    },
    [t],
  );

  const clearSelection = useCallback(() => {
    requestVersionRef.current += 1;
    selectedSessionIdRef.current = null;
    setSelectedSessionId(null);
    setDetail(null);
    setError(null);
    setIsLoading(false);
  }, []);

  return {
    clearSelection,
    detail,
    error,
    isLoading,
    refresh: loadHistory,
    refreshDetail,
    selectSession,
    selectedSessionId,
    sessions,
  };
}
