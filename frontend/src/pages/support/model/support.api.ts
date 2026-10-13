import { runtimeConfig } from '../../../shared/config';
import {
  toRun,
  type Audit,
  type Decision,
  type Run,
  type RunDto,
  type SessionDto,
  type Ticket,
  type TicketInput,
} from './support.types';

const baseUrl = `${runtimeConfig.api.baseUrl?.replace(/\/$/, '') ?? ''}/support-api`;

export class SupportApiError extends Error {
  constructor(public readonly status: number) {
    super(`Support API: ${status}`);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    credentials: 'include',
    signal: options.signal ?? AbortSignal.timeout(runtimeConfig.api.timeoutMs),
  });
  if (!response.ok) throw new SupportApiError(response.status);
  return response.json() as Promise<T>;
}

function post(body: unknown, csrf?: string): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    body: JSON.stringify(body),
  };
}

export const supportApi = {
  session: (): Promise<SessionDto> => request('/auth/session'),
  login: (username: string, password: string): Promise<SessionDto> =>
    request('/auth/login', post({ username, password })),
  logout: (csrf: string): Promise<unknown> => request('/auth/logout', post({}, csrf)),
  tickets: (): Promise<Ticket[]> => request('/tickets'),
  createTicket: (input: TicketInput, csrf: string): Promise<Ticket> =>
    request('/tickets', post(input, csrf)),
  runs: async (ticketId: string): Promise<Run[]> =>
    (await request<RunDto[]>(`/tickets/${ticketId}/runs`)).map(toRun),
  run: async (runId: string): Promise<Run> => toRun(await request<RunDto>(`/runs/${runId}`)),
  start: async (ticketId: string, csrf: string, key: string): Promise<Run> => {
    const options = post({}, csrf);
    return toRun(
      await request<RunDto>(`/tickets/${ticketId}/runs`, {
        ...options,
        headers: { ...options.headers, 'Idempotency-Key': key },
      }),
    );
  },
  approve: async (
    runId: string,
    decision: Decision,
    proposalHash: string,
    feedback: string,
    csrf: string,
  ): Promise<Run> =>
    toRun(
      await request<RunDto>(
        `/runs/${runId}/approval`,
        post({ decision, proposal_hash: proposalHash, feedback: feedback || null }, csrf),
      ),
    ),
  cancel: async (runId: string, csrf: string): Promise<Run> =>
    toRun(await request<RunDto>(`/runs/${runId}/cancel`, post({}, csrf))),
  audit: (runId: string): Promise<Audit[]> => request(`/runs/${runId}/audit`),
  eventsUrl: (runId: string): string => `${baseUrl}/runs/${runId}/events`,
};
