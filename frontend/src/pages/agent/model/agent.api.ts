import { runtimeConfig } from '../../../shared/config';
import { request } from '../../../shared/api';
import type { RunCreatedDto, RunRequestDto, SessionDto } from './agent.types';

export async function createAgentSession() {
  const response = await request<SessionDto>({
    method: 'POST',
    url: '/sessions',
  });

  return {
    sessionId: response.session_id,
  };
}

export async function createAgentRun(sessionId: string, task: string) {
  const payload: RunRequestDto = { task };
  const response = await request<RunCreatedDto, RunRequestDto>({
    method: 'POST',
    url: `/sessions/${encodeURIComponent(sessionId)}/runs`,
    data: payload,
  });

  return {
    runId: response.run_id,
    sessionId: response.session_id,
    status: response.status,
  };
}

export function createAgentEventsUrl(runId: string) {
  const baseUrl = runtimeConfig.api.baseUrl?.replace(/\/$/, '') ?? '';
  return `${baseUrl}/runs/${encodeURIComponent(runId)}/events`;
}
