import { Activity, AlertCircle, CheckCircle2, Circle, Terminal, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { AgentEvent } from '../../model';
import styles from './RunTimeline.module.css';

type RunTimelineProps = {
  events: AgentEvent[];
};

function eventTitle(type: AgentEvent['type'], t: (key: string) => string) {
  const labels = {
    text: t('agent.timeline.text'),
    tool_call: t('agent.timeline.toolCall'),
    tool_result: t('agent.timeline.toolResult'),
    context_usage: t('agent.timeline.contextUsage'),
    done: t('agent.timeline.done'),
  } as const;
  return labels[type];
}

function EventIcon({ type }: { type: AgentEvent['type'] }) {
  if (type === 'text') return <Circle size={16} aria-hidden="true" />;
  if (type === 'tool_call') return <Wrench size={16} aria-hidden="true" />;
  if (type === 'tool_result') return <Terminal size={16} aria-hidden="true" />;
  if (type === 'context_usage') return <Activity size={16} aria-hidden="true" />;
  return <CheckCircle2 size={16} aria-hidden="true" />;
}

function EventBody({ event }: { event: AgentEvent }) {
  if (event.type === 'text') {
    return <p className={styles.text}>{event.data.text}</p>;
  }

  if (event.type === 'tool_call') {
    return (
      <div className={styles.detailList}>
        {event.data.calls.map((call) => (
          <div className={styles.detailRow} key={call.tool_use_id}>
            <strong>{call.name}</strong>
            <code>{call.arguments}</code>
          </div>
        ))}
      </div>
    );
  }

  if (event.type === 'tool_result') {
    return (
      <div className={styles.detailList}>
        {event.data.results.map((result) => (
          <pre className={styles.result} key={result.tool_use_id}>
            {result.content}
          </pre>
        ))}
      </div>
    );
  }

  if (event.type === 'context_usage') {
    const contextTokens =
      event.data.context_tokens !== null
        ? event.data.context_tokens.toLocaleString()
        : 'unknown';
    const contextWindow = event.data.context_window_tokens.toLocaleString();
    const usage =
      event.data.context_usage_percent !== null
        ? `${event.data.context_usage_percent.toFixed(2)}%`
        : 'unknown';
    return (
      <p className={styles.contextUsage}>
        {contextTokens} / {contextWindow} tokens ({usage})
      </p>
    );
  }

  const { error, status } = event.data;
  return (
    <div className={status === 'completed' ? styles.success : styles.failure}>
      {status === 'completed' ? (
        <CheckCircle2 size={17} aria-hidden="true" />
      ) : (
        <AlertCircle size={17} aria-hidden="true" />
      )}
      <span>{error ?? status}</span>
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
