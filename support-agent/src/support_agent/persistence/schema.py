"""Minimal W15 business schema kept separate from LangGraph checkpoints."""

from psycopg import AsyncConnection


APPROVALS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY,
    organization_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    feedback TEXT,
    proposal_hash TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT approvals_decision_check
        CHECK (decision IN ('approve', 'reject', 'revise')),
    CONSTRAINT approvals_feedback_check
        CHECK (
            decision = 'approve'
            OR NULLIF(BTRIM(feedback), '') IS NOT NULL
        ),
    CONSTRAINT approvals_proposal_hash_check
        CHECK (proposal_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT approvals_run_proposal_unique
        UNIQUE (run_id, proposal_hash)
)
"""


TOOL_ACTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tool_actions (
    id UUID PRIMARY KEY,
    organization_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json JSONB NOT NULL,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT tool_actions_status_check
        CHECK (status IN ('pending', 'succeeded', 'failed', 'unknown')),
    CONSTRAINT tool_actions_idempotency_key_check
        CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT tool_actions_idempotency_key_unique
        UNIQUE (idempotency_key)
)
"""


CRM_TICKETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS crm_tickets (
    organization_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    status TEXT NOT NULL,
    update_count INTEGER NOT NULL,
    last_idempotency_key TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, ticket_id),
    CONSTRAINT crm_tickets_update_count_check
        CHECK (update_count >= 1),
    CONSTRAINT crm_tickets_idempotency_key_check
        CHECK (last_idempotency_key ~ '^[0-9a-f]{64}$')
)
"""


async def initialize_business_schema(database_url: str) -> None:
    """Create the small business tables used by the W15 learning flow."""

    async with await AsyncConnection.connect(database_url) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(APPROVALS_TABLE_SQL)
            await cursor.execute(TOOL_ACTIONS_TABLE_SQL)
            await cursor.execute(CRM_TICKETS_TABLE_SQL)
