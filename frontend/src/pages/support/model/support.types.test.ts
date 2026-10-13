import { describe, expect, it } from 'vitest';
import { decodeTimelineEvent, mergeEvents, toRun, type RunDto } from './support.types';

describe('support event replay', () => {
  it('deduplicates repeated sequence numbers and keeps replay ordered', () => {
    const later = { sequence: 2, kind: 'done', payload: {} };
    const first = { sequence: 1, kind: 'status', payload: {} };
    const events = mergeEvents(mergeEvents([], later), first);
    expect(events.map((event) => event.sequence)).toEqual([1, 2]);
    expect(mergeEvents(events, later)).toBe(events);
    expect(mergeEvents(events, { ...later, sequence: NaN })).toBe(events);
  });
  it('does not promote an unknown backend status to success', () => {
    expect(toRun({ status: 'brand-new-state' } as RunDto).status).toBe('unknown');
  });
  it('rejects malformed terminal frames and normalizes unknown event statuses', () => {
    expect(decodeTimelineEvent(0, 'done', '{"status":"succeeded"}')).toBeNull();
    expect(decodeTimelineEvent(1, 'done', '{"status":"running"}')).toBeNull();
    expect(decodeTimelineEvent(1, 'response', 'not-json')).toBeNull();
    expect(decodeTimelineEvent(1, 'status', '{"status":"new-status"}')?.payload.status).toBe(
      'unknown',
    );
  });
});
