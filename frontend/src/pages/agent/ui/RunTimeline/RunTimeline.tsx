import { AlertCircle, CheckCircle2, Circle, Terminal, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { AgentEvent } from '../../model';
import styles from './RunTimeline.module.css';

type RunTimelineProps = {
  events: AgentEvent[];
};

type EventRecord = Record<string, unknown>;

function asRecord(value: unknown): EventRecord | null {
  return typeof value === 'object' && value !== null ? (value as EventRecord) : null;
}

function asRecordList(value: unknown): EventRecord[] {
  if (!Array.isArray(value)) return [];
  return value.map(asRecord).filter((item): item is EventRecord => item !== null);
}

function asText(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function eventTitle(type: AgentEvent['type'], t: (key: string) => string) {
  const labels = {
    text: t('agent.timeline.text'),
    tool_call: t('agent.timeline.toolCall'),
    tool_result: t('agent.timeline.toolResult'),
    done: t('agent.timeline.done'),
  } as const;
  return labels[type];
}

function EventIcon({ type }: { type: AgentEvent['type'] }) {
  if (type === 'text') return <Circle size={16} aria-hidden="true" />;
  if (type === 'tool_call') return <Wrench size={16} aria-hidden="true" />;
  if (type === 'tool_result') return <Terminal size={16} aria-hidden="true" />;
  return <CheckCircle2 size={16} aria-hidden="true" />;
}

function EventBody({ event }: { event: AgentEvent }) {
  const text = asText(event.data.text);
  if (event.type === 'text') {
    return <p className={styles.text}>{text}</p>;
  }

  if (event.type === 'tool_call') {
    const calls = asRecordList(event.data.calls);
    return (
      <div className={styles.detailList}>
        {calls.map((call, index) => (
          <div className={styles.detailRow} key={asText(call.id, String(index))}>
            <strong>{asText(call.name)}</strong>
            <code>{asText(call.arguments, '{}')}</code>
          </div>
        ))}
      </div>
    );
  }

  if (event.type === 'tool_result') {
    const results = asRecordList(event.data.results);
    return (
      <div className={styles.detailList}>
        {results.map((result, index) => (
          <pre className={styles.result} key={asText(result.tool_call_id, String(index))}>
            {asText(result.content)}
          </pre>
        ))}
      </div>
    );
  }

  const status = asText(event.data.status, 'completed');
  const error = asText(event.data.error);
  return (
    <div className={status === 'completed' ? styles.success : styles.failure}>
      {status === 'completed' ? (
        <CheckCircle2 size={17} aria-hidden="true" />
      ) : (
        <AlertCircle size={17} aria-hidden="true" />
      )}
      <span>{error || status}</span>
    </div>
  );
}

export function RunTimeline({ events }: RunTimelineProps) {
  const { t } = useTranslation();

  if (events.length === 0) {
    return (
      <section className={styles.empty} aria-live="polite">
        <Circle size={24} aria-hidden="true" />
        <h2>{t('agent.timeline.emptyTitle')}</h2>
        <p>{t('agent.timeline.emptyDescription')}</p>
      </section>
    );
  }

  return (
    <section className={styles.root} aria-label={t('agent.timeline.label')} aria-live="polite">
      <div className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t('agent.timeline.eyebrow')}</p>
          <h2 className={styles.title}>{t('agent.timeline.title')}</h2>
        </div>
        <span className={styles.count}>{events.length}</span>
      </div>
      <ol className={styles.list}>
        {events.map((event) => (
          <li className={styles.item} key={`${event.runId}-${event.sequence}`}>
            <div className={styles.marker} aria-hidden="true">
              <EventIcon type={event.type} />
            </div>
            <div className={styles.eventContent}>
              <div className={styles.eventHeader}>
                <h3>{eventTitle(event.type, t)}</h3>
                <span>#{event.sequence + 1}</span>
              </div>
              <EventBody event={event} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
