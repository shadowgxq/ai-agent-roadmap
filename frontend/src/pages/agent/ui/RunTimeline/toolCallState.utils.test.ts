import { describe, expect, it } from 'vitest';

import type { AgentEvent } from '../../model';
import { buildTimelineItems } from './toolCallState.utils';

function toolCall(sequence: number, toolUseId = 'call-1'): AgentEvent {
  return {
    sequence,
    runId: 'run-1',
    type: 'tool_call',
    data: {
      turn: 1,
      calls: [
        {
          tool_use_id: toolUseId,
          name: 'read_file',
          arguments: '{"path":"README.md"}',
        },
      ],
    },
  };
}

function toolResult(
  sequence: number,
  isError: boolean,
  toolUseId = 'call-1',
): AgentEvent {
  return {
    sequence,
    runId: 'run-1',
    type: 'tool_result',
    data: {
      turn: 1,
      results: [
        {
          tool_use_id: toolUseId,
          content: isError ? '读取失败' : 'README 内容',
          is_error: isError,
        },
      ],
    },
  };
}

function done(sequence: number): AgentEvent {
  return {
    sequence,
    runId: 'run-1',
    type: 'done',
    data: { status: 'completed', turn: 1 },
  };
}

function getToolItem(events: AgentEvent[]) {
  const item = buildTimelineItems(events).find((timelineItem) => timelineItem.kind === 'tool');
  if (!item || item.kind !== 'tool') throw new Error('tool item not found');
  return item.tool;
}

describe('buildTimelineItems', () => {
  it('pairs a tool result by tool_use_id and maps success', () => {
    const tool = getToolItem([toolCall(1), toolResult(2, false), done(3)]);

    expect(tool.status).toBe('success');
    expect(tool.result?.is_error).toBe(false);
    expect(tool.warning).toBeUndefined();
  });

  it('maps an error result to failed without parsing result text', () => {
    const tool = getToolItem([toolCall(1), toolResult(2, true), done(3)]);

    expect(tool.status).toBe('failed');
    expect(tool.result?.content).toBe('读取失败');
  });

  it('does not crash on missing or duplicate tool events', () => {
    const missingResult = getToolItem([toolCall(1), done(2)]);
    const orphanResult = getToolItem([toolResult(1, false), done(2)]);
    const duplicateResult = getToolItem([
      toolCall(1),
      toolResult(2, false),
      toolResult(3, true),
      done(4),
    ]);

    expect(missingResult).toMatchObject({ status: 'failed', warning: 'missing_result' });
    expect(orphanResult).toMatchObject({ status: 'failed', warning: 'missing_call' });
    expect(duplicateResult).toMatchObject({ status: 'success', warning: 'duplicate_result' });
  });
});
