export const runStatuses = [
  'queued',
  'running',
  'waiting_approval',
  'succeeded',
  'failed',
  'cancelled',
  'unknown',
] as const;
export type RunStatus = (typeof runStatuses)[number];
export type Decision = 'approve' | 'reject' | 'revise';
export type Identity = {
  organization_id: string;
  user_id: string;
  role: 'viewer' | 'operator' | 'approver' | 'admin';
};
export type SessionDto = { identity: Identity; csrf_token: string };
export type Ticket = {
  ticket_id: string;
  subject: string;
  description: string;
  knowledge_base_id: string;
};
export type TicketInput = Omit<Ticket, 'ticket_id'>;
export type Evidence = {
  chunk_id?: string;
  source_id: string;
  document_title?: string;
  title: string;
  document_version?: number;
  heading_path?: string[];
  page?: number;
  snippet: string;
};
export type Projection = {
  draft_response?: string;
  evidence_refs?: Evidence[];
  proposal_hash?: string;
  error_code?: string;
};
export type RunDto = {
  run_id: string;
  ticket_id: string;
  status: string;
  projection: Projection;
  sequence: number;
  cancel_requested: boolean;
};
export type Run = Omit<RunDto, 'status'> & { status: RunStatus };
export type Audit = {
  actor_id: string;
  action: string;
  created_at: string;
  payload: Record<string, unknown>;
};
export type TimelineEvent = {
  sequence: number;
  kind: string;
  payload: Projection & { status?: RunStatus };
};

export function toRun(dto: RunDto): Run {
  return { ...dto, status: runStatuses.find((status) => status === dto.status) ?? 'unknown' };
}

export function mergeEvents(current: TimelineEvent[], incoming: TimelineEvent): TimelineEvent[] {
  if (
    !Number.isSafeInteger(incoming.sequence) ||
    incoming.sequence < 1 ||
    current.some((event) => event.sequence === incoming.sequence)
  )
    return current;
  return [...current, incoming].sort((left, right) => left.sequence - right.sequence);
}

export function decodeTimelineEvent(
  sequence: number,
  kind: string,
  text: string,
): TimelineEvent | null {
  if (
    !Number.isSafeInteger(sequence) ||
    sequence < 1 ||
    !['status', 'response', 'cancel_requested', 'done'].includes(kind)
  )
    return null;
  try {
    const payload: unknown = JSON.parse(text);
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
    const source = payload as Record<string, unknown>;
    const status =
      typeof source.status === 'string'
        ? (runStatuses.find((value) => value === source.status) ?? 'unknown')
        : undefined;
    if (kind === 'done' && (!status || !['succeeded', 'failed', 'cancelled'].includes(status)))
      return null;
    return {
      sequence,
      kind,
      payload: {
        ...(status ? { status } : {}),
        ...(typeof source.draft_response === 'string'
          ? { draft_response: source.draft_response }
          : {}),
      },
    };
  } catch {
    return null;
  }
}
