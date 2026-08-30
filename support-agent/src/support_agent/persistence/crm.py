"""Transactional idempotency adapter for the local W15 mock CRM."""

from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from support_agent.models import (
    CrmTicketRecord,
    CrmUpdateResult,
    ToolActionRecord,
)

from .tool_actions import ToolActionConflictError


class ToolActionInProgressError(RuntimeError):
    """An identical durable action exists but has no known result yet."""


class ToolActionOutcomeUnknownError(RuntimeError):
    """An external outcome is unknown and must not be retried blindly."""


class ToolActionPreviouslyFailedError(RuntimeError):
    """A failed action requires an explicit retry policy or a new action."""


class MockCrmRepository:
    """Update the local CRM and tool-action record in one transaction."""

    ACTION_TYPE = "update_crm_ticket"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def update_ticket(
        self,
        *,
        organization_id: str,
        ticket_id: str,
        run_id: str,
        status: str,
        idempotency_key: str,
    ) -> CrmUpdateResult:
        """Execute once, or return the committed result for the same key."""

        request_json = {"ticket_id": ticket_id, "status": status}
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
                        self.ACTION_TYPE,
                        idempotency_key,
                        Jsonb(request_json),
                    ),
                )
                action_row = await cursor.fetchone()
                if action_row is None:
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
                        raise RuntimeError(
                            "工具行为唯一约束冲突后没有找到已有记录。"
                        )
                    return self._result_for_existing(
                        ToolActionRecord.model_validate(existing_row),
                        organization_id=organization_id,
                        ticket_id=ticket_id,
                        run_id=run_id,
                        request_json=request_json,
                    )

                await cursor.execute(
                    """
                    INSERT INTO crm_tickets (
                        organization_id,
                        ticket_id,
                        status,
                        update_count,
                        last_idempotency_key
                    )
                    VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (organization_id, ticket_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        update_count = crm_tickets.update_count + 1,
                        last_idempotency_key = EXCLUDED.last_idempotency_key,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        organization_id,
                        ticket_id,
                        status,
                        idempotency_key,
                    ),
                )
                crm_row = await cursor.fetchone()
                if crm_row is None:
                    raise RuntimeError("模拟 CRM 更新后没有返回工单记录。")
                crm_ticket = CrmTicketRecord.model_validate(crm_row)
                persisted_result = {
                    "organization_id": crm_ticket.organization_id,
                    "ticket_id": crm_ticket.ticket_id,
                    "status": crm_ticket.status,
                    "update_count": crm_ticket.update_count,
                    "idempotency_key": idempotency_key,
                }

                await cursor.execute(
                    """
                    UPDATE tool_actions
                    SET status = 'succeeded',
                        result_json = %s,
                        completed_at = now()
                    WHERE idempotency_key = %s
                    """,
                    (Jsonb(persisted_result), idempotency_key),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("模拟 CRM 成功后无法完成工具行为记录。")

        return CrmUpdateResult.model_validate({
            **persisted_result,
            "replayed": False,
        })

    async def get_ticket(
        self,
        *,
        organization_id: str,
        ticket_id: str,
    ) -> CrmTicketRecord | None:
        """Read the current mock CRM ticket without changing it."""

        async with await AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT *
                    FROM crm_tickets
                    WHERE organization_id = %s AND ticket_id = %s
                    """,
                    (organization_id, ticket_id),
                )
                row = await cursor.fetchone()
        return CrmTicketRecord.model_validate(row) if row is not None else None

    def _result_for_existing(
        self,
        action: ToolActionRecord,
        *,
        organization_id: str,
        ticket_id: str,
        run_id: str,
        request_json: dict[str, object],
    ) -> CrmUpdateResult:
        if (
            action.organization_id != organization_id
            or action.ticket_id != ticket_id
            or action.run_id != run_id
            or action.action_type != self.ACTION_TYPE
            or action.request_json != request_json
        ):
            raise ToolActionConflictError(
                "同一 idempotency_key 已绑定不同的 CRM 请求。"
            )

        if action.status == "succeeded":
            if action.result_json is None:
                raise RuntimeError("成功的工具行为缺少 result_json。")
            return CrmUpdateResult.model_validate({
                **action.result_json,
                "replayed": True,
            })
        if action.status == "pending":
            raise ToolActionInProgressError(
                "相同 CRM 工具行为仍是 pending，不能盲目重复执行。"
            )
        if action.status == "unknown":
            raise ToolActionOutcomeUnknownError(
                "CRM 工具行为结果未知，需要查询外部状态或人工核对。"
            )
        raise ToolActionPreviouslyFailedError(
            "CRM 工具行为此前失败，需要显式决定是否创建新的重试动作。"
        )
