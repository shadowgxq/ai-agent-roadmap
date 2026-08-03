export const AGENT_EVENT_TYPES = ['text', 'tool_call', 'tool_result', 'done'] as const;

export type AgentEventType = (typeof AGENT_EVENT_TYPES)[number];

export type RunStatus = 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'interrupted';

export type RunRequestDto = {
  task: string;
};

export type RunCreatedDto = {
  run_id: string;
  status: string;
};

export type AgentEventDto = {
  sequence: number;
  run_id: string;
  event: AgentEventType;
  data: Record<string, unknown>;
};

export type AgentEvent = {
  sequence: number;
  runId: string;
  type: AgentEventType;
  data: Record<string, unknown>;
};

export function toRunStatus(value: string): Exclude<RunStatus, 'idle' | 'starting'> {
  if (value === 'completed' || value === 'failed' || value === 'interrupted') {
    return value;
  }
  return 'running';
}

export function toAgentEvent(dto: AgentEventDto): AgentEvent {
  return {
    sequence: dto.sequence,
    runId: dto.run_id,
    type: dto.event,
    data: dto.data,
  };
}
