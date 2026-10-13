"""W20 business truth and event/outbox durability live together in PostgreSQL."""

APPLICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS support_tickets (
 organization_id TEXT NOT NULL, ticket_id UUID NOT NULL, user_id TEXT NOT NULL,
 subject TEXT NOT NULL, description TEXT NOT NULL, knowledge_base_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(organization_id,ticket_id),
 FOREIGN KEY(organization_id,knowledge_base_id) REFERENCES knowledge_bases(organization_id,knowledge_base_id)
);
CREATE TABLE IF NOT EXISTS support_runs (
 organization_id TEXT NOT NULL, run_id UUID NOT NULL, ticket_id UUID NOT NULL,
 thread_id UUID NOT NULL UNIQUE, user_id TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','waiting_approval','succeeded','failed','cancelled')),
 idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 sequence BIGINT NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 1,
 attempt INTEGER NOT NULL DEFAULT 0, cancel_requested BOOLEAN NOT NULL DEFAULT false,
 lease_token UUID, lease_until TIMESTAMPTZ, projection JSONB NOT NULL DEFAULT '{}',
 resume_payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(organization_id,run_id),
 UNIQUE(organization_id,idempotency_key),
 FOREIGN KEY(organization_id,ticket_id) REFERENCES support_tickets(organization_id,ticket_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS support_one_active_run
 ON support_runs(organization_id,ticket_id) WHERE status IN ('queued','running','waiting_approval');
CREATE TABLE IF NOT EXISTS support_run_events (
 organization_id TEXT NOT NULL, run_id UUID NOT NULL, sequence BIGINT NOT NULL,
 kind TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(organization_id,run_id,sequence),
 FOREIGN KEY(organization_id,run_id) REFERENCES support_runs(organization_id,run_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS support_done_once
 ON support_run_events(organization_id,run_id) WHERE kind='done';
CREATE TABLE IF NOT EXISTS support_outbox (
 organization_id TEXT NOT NULL, run_id UUID NOT NULL, generation INTEGER NOT NULL,
 dispatched BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(organization_id,run_id,generation),
 FOREIGN KEY(organization_id,run_id) REFERENCES support_runs(organization_id,run_id)
);
CREATE TABLE IF NOT EXISTS support_audit (
 organization_id TEXT NOT NULL, run_id UUID NOT NULL, audit_id UUID NOT NULL,
 actor_id TEXT NOT NULL, action TEXT NOT NULL, payload JSONB NOT NULL,
 idempotency_key TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(organization_id,audit_id), UNIQUE(organization_id,idempotency_key),
 FOREIGN KEY(organization_id,run_id) REFERENCES support_runs(organization_id,run_id)
);
CREATE INDEX IF NOT EXISTS support_runs_recovery ON support_runs(status,lease_until);
"""
