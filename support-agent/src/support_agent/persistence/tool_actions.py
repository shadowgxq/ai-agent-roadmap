"""PostgreSQL access for idempotent external-action state."""

from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from support_agent.models import ToolActionRecord, ToolActionStatus


class ToolActionConflictError(RuntimeError):
    """One idempotency key was reused for a different request."""


class ToolActionRepository:
    """Reserve and update one durable tool action per idempotency key."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def reserve_action(
        self,
        *,
        organization_id: str,
        ticket_id: str,
        run_id: str,
        action_type: str,
        idempotency_key: str,
        request_json: dict[str, object],
    ) -> tuple[ToolActionRecord, bool]:
        """Create pending once, or return the identical existing action."""

        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO tool_actions (
                        id,
                        organization_id,
                        ticket_id,
                        run_id,
                        action_type,
                        idempotency_key,
                        status,
                        request_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING *
                    """,
                    (
                        uuid4(),
                        organization_id,
                        ticket_id,
                        run_id,
                        action_type,
                        idempotency_key,
                        Jsonb(request_json),
                    ),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return ToolActionRecord.model_validate(row), True

                await cursor.execute(
                    """
                    SELECT *
                    FROM tool_actions
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                existing_row = await cursor.fetchone()

        if existing_row is None:
            raise RuntimeError("工具行为唯一约束冲突后没有找到已有记录。")

        existing = ToolActionRecord.model_validate(existing_row)
        if (
            existing.organization_id != organization_id
            or existing.ticket_id != ticket_id
            or existing.run_id != run_id
            or existing.action_type != action_type
            or existing.request_json != request_json
        ):
            raise ToolActionConflictError(
                "同一 idempotency_key 已绑定不同的工具请求。"
            )
        return existing, False

    async def get_by_key(
        self,
        idempotency_key: str,
    ) -> ToolActionRecord | None:
        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT *
                    FROM tool_actions
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = await cursor.fetchone()
        return ToolActionRecord.model_validate(row) if row is not None else None

    async def mark_status(
        self,
        *,
        idempotency_key: str,
        status: ToolActionStatus,
        result_json: dict[str, object] | None = None,
    ) -> ToolActionRecord:
        """Persist the latest known outcome without executing the tool itself."""

        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE tool_actions
                    SET status = %s,
                        result_json = %s,
                        completed_at = CASE
                            WHEN %s IN ('succeeded', 'failed') THEN now()
                            ELSE NULL
                        END
                    WHERE idempotency_key = %s
                    RETURNING *
                    """,
                    (
                        status,
                        Jsonb(result_json) if result_json is not None else None,
                        status,
                        idempotency_key,
                    ),
                )
                row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"没有找到 idempotency_key={idempotency_key!r}。")
        return ToolActionRecord.model_validate(row)
