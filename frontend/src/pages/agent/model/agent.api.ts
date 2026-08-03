import { runtimeConfig } from '../../../shared/config';
import { request } from '../../../shared/api';
import type { RunCreatedDto, RunRequestDto } from './agent.types';

export async function createAgentRun(task: string) {
  const payload: RunRequestDto = { task };
  const response = await request<RunCreatedDto, RunRequestDto>({
    method: 'POST',
    url: '/runs',
    data: payload,
  });

  return {
    runId: response.run_id,
    status: response.status,
  };
}

export function createAgentEventsUrl(runId: string) {
  const baseUrl = runtimeConfig.api.baseUrl?.replace(/\/$/, '') ?? '';
  return `${baseUrl}/runs/${encodeURIComponent(runId)}/events`;
}
