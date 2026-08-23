import type {
  AgentEvent,
  ToolCallCardModel,
  ToolCallItem,
  ToolResultItem,
} from '../../model';

export type NonToolAgentEvent = Exclude<
  AgentEvent,
  { type: 'tool_call' } | { type: 'tool_result' }
>;

export type RunTimelineItem =
  | { kind: 'event'; event: NonToolAgentEvent }
  | { kind: 'tool'; tool: ToolCallCardModel };

function createToolCard(
  call: ToolCallItem | null,
  result: ToolResultItem | null,
  sequence: number,
): ToolCallCardModel {
  return {
    toolUseId: call?.tool_use_id ?? result?.tool_use_id ?? 'unknown-tool-use',
    call,
    result,
    sequence,
    status: result ? (result.is_error ? 'failed' : 'success') : 'running',
  };
}

export function buildTimelineItems(events: AgentEvent[]): RunTimelineItem[] {
  const orderedEvents = [...events].sort(
    (left, right) => left.sequence - right.sequence,
  );
  const items: RunTimelineItem[] = [];
  const toolCardById = new Map<string, ToolCallCardModel>();

  for (const event of orderedEvents) {
    if (event.type === 'tool_call') {
      for (const call of event.data.calls) {
        const existingCard = toolCardById.get(call.tool_use_id);
        if (existingCard) {
          if (existingCard.call === null) {
            existingCard.call = call;
            existingCard.warning = undefined;
            existingCard.sequence = Math.min(existingCard.sequence, event.sequence);
          } else {
            existingCard.warning = 'duplicate_call';
          }
          continue;
        }

        const card = createToolCard(call, null, event.sequence);
        toolCardById.set(call.tool_use_id, card);
        items.push({ kind: 'tool', tool: card });
      }
      continue;
    }

    if (event.type === 'tool_result') {
      for (const result of event.data.results) {
        const existingCard = toolCardById.get(result.tool_use_id);
        if (!existingCard) {
          const orphanCard = createToolCard(null, result, event.sequence);
          orphanCard.warning = 'missing_call';
          orphanCard.status = 'failed';
          toolCardById.set(result.tool_use_id, orphanCard);
          items.push({ kind: 'tool', tool: orphanCard });
        } else if (existingCard.result) {
          existingCard.warning = 'duplicate_result';
        } else {
          existingCard.result = result;
          existingCard.status = result.is_error ? 'failed' : 'success';
        }
      }
      continue;
    }

    items.push({ kind: 'event', event });
  }

  const hasFinished = orderedEvents.some((event) => event.type === 'done');
  if (hasFinished) {
    for (const card of toolCardById.values()) {
      if (!card.result && !card.warning) {
        card.status = 'failed';
        card.warning = 'missing_result';
      }
    }
  }

  return items;
}
