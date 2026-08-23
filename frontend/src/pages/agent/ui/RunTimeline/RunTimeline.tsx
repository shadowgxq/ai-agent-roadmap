import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Circle,
  GitCompareArrows,
  ShieldAlert,
  Wrench,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { AgentEvent } from '../../model';
import { DiffView } from '../DiffView';
import { ToolCallCard } from '../ToolCallCard';
import type { NonToolAgentEvent, RunTimelineItem } from './toolCallState.utils';
import { buildTimelineItems } from './toolCallState.utils';
import styles from './RunTimeline.module.css';

type RunTimelineProps = {
  events: AgentEvent[];
};

type Translate = (key: string) => string;

function eventTitle(type: NonToolAgentEvent['type'], t: Translate) {
  const labels: Record<NonToolAgentEvent['type'], string> = {
    text: t('agent.timeline.text'),
    status: t('agent.timeline.status.title'),
    context_usage: t('agent.timeline.contextUsage'),
    diff: t('agent.timeline.diff'),
    done: t('agent.timeline.done'),
  };
  return labels[type];
}

function EventIcon({ type }: { type: NonToolAgentEvent['type'] }) {
  if (type === 'text') return <Circle size={16} aria-hidden="true" />;
  if (type === 'status') return <ShieldAlert size={16} aria-hidden="true" />;
  if (type === 'context_usage') return <Activity size={16} aria-hidden="true" />;
  if (type === 'diff') return <GitCompareArrows size={16} aria-hidden="true" />;
  return <CheckCircle2 size={16} aria-hidden="true" />;
}

function EventBody({ event, t }: { event: NonToolAgentEvent; t: Translate }) {
  if (event.type === 'text') {
    return <p className={styles.text}>{event.data.text}</p>;
  }

  if (event.type === 'context_usage') {
    const contextTokens =
      event.data.context_tokens !== null ? event.data.context_tokens.toLocaleString() : 'unknown';
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

  if (event.type === 'status') {
    const statusKeys: Record<typeof event.data.status, string> = {
      queued: 'agent.timeline.status.queued',
      running: 'agent.timeline.status.running',
      waiting_confirmation: 'agent.timeline.status.waitingConfirmation',
    };
    return <p className={styles.contextUsage}>{t(statusKeys[event.data.status])}</p>;
  }

  if (event.type === 'diff') {
    return <DiffView files={event.data.files} />;
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

function TimelineListItem({ item, t }: { item: RunTimelineItem; t: Translate }) {
  if (item.kind === 'tool') {
    return (
      <li className={styles.item}>
        <div className={styles.marker} aria-hidden="true">
          <Wrench size={16} />
        </div>
        <div className={styles.eventContent}>
          <ToolCallCard tool={item.tool} />
        </div>
      </li>
    );
  }

  const { event } = item;
  return (
    <li className={styles.item}>
      <div className={styles.marker} aria-hidden="true">
        <EventIcon type={event.type} />
      </div>
      <div className={styles.eventContent}>
        <div className={styles.eventHeader}>
          <h3>{eventTitle(event.type, t)}</h3>
          <span>#{event.sequence + 1}</span>
        </div>
        <EventBody event={event} t={t} />
      </div>
    </li>
  );
}

function timelineItemKey(item: RunTimelineItem) {
  return item.kind === 'tool'
    ? `tool-${item.tool.toolUseId}-${item.tool.sequence}`
    : `${item.event.runId}-${item.event.sequence}`;
}

export function RunTimeline({ events }: RunTimelineProps) {
  const { t } = useTranslation();
  const timelineItems = buildTimelineItems(events);

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
        <span className={styles.count}>{timelineItems.length}</span>
      </div>
      <ol className={styles.list}>
        {timelineItems.map((item) => (
          <TimelineListItem item={item} key={timelineItemKey(item)} t={t} />
        ))}
      </ol>
    </section>
  );
}
