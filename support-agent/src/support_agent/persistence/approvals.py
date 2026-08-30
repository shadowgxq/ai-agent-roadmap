"""PostgreSQL access for durable human approval facts."""

from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from support_agent.models import ApprovalDecision, ApprovalRecord


class ApprovalConflictError(RuntimeError):
    """The same proposal already has a different durable decision."""


class ApprovalRepository:
    """Store one authoritative decision per run and proposal hash."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def record_decision(
        self,
        *,
        organization_id: str,
        ticket_id: str,
        run_id: str,
        thread_id: str,
        actor_id: str,
        decision: ApprovalDecision,
        feedback: str | None,
        proposal_hash: str,
    ) -> tuple[ApprovalRecord, bool]:
        """Insert atomically, returning the existing identical decision on retry."""

        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO approvals (
                        id,
                        organization_id,
                        ticket_id,
                        run_id,
                        thread_id,
                        actor_id,
                        decision,
                        feedback,
                        proposal_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, proposal_hash) DO NOTHING
                    RETURNING *
                    """,
                    (
                        uuid4(),
                        organization_id,
                        ticket_id,
                        run_id,
                        thread_id,
                        actor_id,
                        decision,
                        feedback,
                        proposal_hash,
                    ),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return ApprovalRecord.model_validate(row), True

                await cursor.execute(
                    """
                    SELECT *
                    FROM approvals
                    WHERE run_id = %s AND proposal_hash = %s
                    """,
                    (run_id, proposal_hash),
                )
                existing_row = await cursor.fetchone()

        if existing_row is None:
            raise RuntimeError("审批唯一约束冲突后没有找到已有记录。")

        existing = ApprovalRecord.model_validate(existing_row)
        if (
            existing.organization_id != organization_id
            or existing.ticket_id != ticket_id
            or existing.thread_id != thread_id
            or existing.actor_id != actor_id
            or existing.decision != decision
            or existing.feedback != feedback
        ):
            raise ApprovalConflictError(
                "同一 run 和 proposal 已存在不同的审批决定。"
            )
        return existing, False

    async def list_for_run(self, run_id: str) -> list[ApprovalRecord]:
        """Return the audit trail for one run in decision order."""

        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT *
                    FROM approvals
                    WHERE run_id = %s
                    ORDER BY decided_at, id
                    """,
                    (run_id,),
                )
                rows = await cursor.fetchall()
        return [ApprovalRecord.model_validate(row) for row in rows]
