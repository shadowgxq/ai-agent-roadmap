import { runtimeConfig } from '../../../shared/config';
import { request } from '../../../shared/api';
import type {
  AgentMessage,
  AgentSession,
  AgentSessionDetail,
  AgentStoredRun,
  MessageDto,
  RunCreatedDto,
  RunDto,
  RunRequestDto,
  SessionDetailDto,
  SessionDto,
} from './agent.types';

function toAgentSession(dto: SessionDto): AgentSession {
  return {
    sessionId: dto.session_id,
    status: dto.status,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

function toAgentMessage(dto: MessageDto): AgentMessage {
  return {
    messageId: dto.message_id,
    sessionId: dto.session_id,
    runId: dto.run_id,
    role: dto.role,
    kind: dto.kind,
    content: dto.content,
    metadata: dto.metadata,
    createdAt: dto.created_at,
  };
}

function toAgentStoredRun(dto: RunDto): AgentStoredRun {
  return {
    runId: dto.run_id,
    sessionId: dto.session_id,
    messageId: dto.message_id,
    task: dto.task,
    status: dto.status,
    createdAt: dto.created_at,
    finishedAt: dto.finished_at,
    confirmationId: dto.confirmation_id,
    confirmationCommand: dto.confirmation_command,
    confirmationReason: dto.confirmation_reason,
  };
}

function toAgentSessionDetail(dto: SessionDetailDto): AgentSessionDetail {
  return {
    session: toAgentSession(dto.session),
    runs: dto.runs.map(toAgentStoredRun),
    messages: dto.messages.map(toAgentMessage),
  };
}

export async function createAgentSession() {
  const response = await request<SessionDto>({
    method: 'POST',
    url: '/sessions',
  });

  return {
    sessionId: response.session_id,
  };
}

export async function listAgentSessions() {
  const response = await request<SessionDto[]>({
    method: 'GET',
    url: '/sessions',
  });

  return response.map(toAgentSession);
}

export async function getActiveAgentRun() {
  const response = await request<RunDto | null>({
    method: 'GET',
    url: '/runs/active',
  });

  return response ? toAgentStoredRun(response) : null;
}

export async function getAgentSessionDetail(sessionId: string) {
  const response = await request<SessionDetailDto>({
    method: 'GET',
    url: `/sessions/${encodeURIComponent(sessionId)}`,
  });

  return toAgentSessionDetail(response);
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

export async function confirmAgentRun(runId: string, approved: boolean) {
  await request<RunDto, { approved: boolean }>({
    method: 'POST',
    url: `/runs/${encodeURIComponent(runId)}/confirm`,
    data: { approved },
  });
}

export async function cancelAgentRun(runId: string) {
  await request<RunDto>({
    method: 'POST',
    url: `/runs/${encodeURIComponent(runId)}/cancel`,
  });
}

export function createAgentEventsUrl(runId: string) {
  const baseUrl = runtimeConfig.api.baseUrl?.replace(/\/$/, '') ?? '';
  return `${baseUrl}/runs/${encodeURIComponent(runId)}/events`;
}
