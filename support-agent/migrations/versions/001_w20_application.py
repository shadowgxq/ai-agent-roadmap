"""W20 initial schema, retaining existing W15/W19 tables and data."""

from alembic import op
from support_agent.application.schema import APPLICATION_SCHEMA
from support_agent.knowledge.schema import KNOWLEDGE_SCHEMA
from support_agent.persistence.schema import APPROVALS_TABLE_SQL, TOOL_ACTIONS_TABLE_SQL, CRM_TICKETS_TABLE_SQL

revision = "001_w20"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for schema in (KNOWLEDGE_SCHEMA, APPROVALS_TABLE_SQL, TOOL_ACTIONS_TABLE_SQL, CRM_TICKETS_TABLE_SQL, APPLICATION_SCHEMA):
        for statement in schema.split(";"):
            if statement.strip():
                op.execute(statement)


def downgrade():
    # Never remove the pre-existing learning/checkpoint/knowledge tables.
    for table in ("support_audit", "support_outbox", "support_run_events", "support_runs", "support_tickets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
