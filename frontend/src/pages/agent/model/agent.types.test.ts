import { describe, expect, it } from 'vitest';

import { parseAgentEvent, toRunStatus } from './agent.types';

describe('parseAgentEvent', () => {
  it('parses a public tool event into the frontend domain shape', () => {
    expect(
      parseAgentEvent({
        sequence: 2,
        run_id: 'run-1',
        event: 'tool_call',
        data: {
          turn: 1,
          calls: [
            {
              tool_use_id: 'call-1',
              name: 'read_file',
              arguments: '{"path":"README.md"}',
            },
          ],
        },
      }),
    ).toEqual({
      sequence: 2,
      runId: 'run-1',
      type: 'tool_call',
      data: {
        turn: 1,
        calls: [
          {
            tool_use_id: 'call-1',
            name: 'read_file',
            arguments: '{"path":"README.md"}',
          },
        ],
      },
    });
  });

  it('rejects unknown event types and incomplete max-turns events', () => {
    expect(() =>
      parseAgentEvent({
        sequence: 0,
        run_id: 'run-1',
        event: 'compact_usage',
        data: {},
      }),
    ).toThrow('event is not a supported Agent Event type');

    expect(() =>
      parseAgentEvent({
        sequence: 1,
        run_id: 'run-1',
        event: 'done',
        data: { status: 'max_turns' },
      }),
    ).toThrow('max_turns terminal status requires data.max_turns');
  });
});

describe('toRunStatus', () => {
  it('maps terminal protocol statuses to UI statuses', () => {
    expect(toRunStatus('completed')).toBe('completed');
    expect(toRunStatus('cancelled')).toBe('interrupted');
    expect(toRunStatus('failed')).toBe('failed');
    expect(toRunStatus('max_turns')).toBe('failed');
  });
});
