"""Project LangGraph runtime events into a stable application event protocol."""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig

from support_agent.models import AgentEvent, AgentEventName, TicketAgentState


Clock = Callable[[], datetime]

NODE_STAGE_BY_NAME: dict[str, str] = {
    "normalize_ticket": "normalizing",
    "classify_ticket": "classifying",
    "build_clarification": "needs_clarification",
    "retrieve_policy_stub": "retrieving_policy",
    "draft_response": "drafting_response",
    "assess_risk": "assessing_risk",
    "prepare_approval": "preparing_approval",
    "approval_gate": "waiting_approval",
    "execute_tool_stub": "approved_action_stub",
    "finalize": "finalizing",
}


class GraphEventAdapter:
    """Convert internal LangGraph events into allowlisted application events."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def stream(
        self,
        graph: Any,
        state: TicketAgentState,
        *,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream public events for one graph run."""

        if config is None:
            source = graph.astream_events(state, version="v2")
        else:
            source = graph.astream_events(state, config=config, version="v2")
        async for event in self.adapt(source, run_id=state["run_id"]):
            yield event

    async def adapt(
        self,
        source: AsyncIterable[Mapping[str, Any]],
        *,
        run_id: str,
    ) -> AsyncIterator[AgentEvent]:
        """Adapt an internal event source and always emit one terminal event."""

        sequence = 0
        workflow_status = "completed"
        error_code: str | None = None
        error_message: str | None = None

        try:
            async for raw_event in source:
                output = self._chain_output(raw_event)
                (
                    workflow_status,
                    error_code,
                    error_message,
                ) = self._capture_workflow_result(
                    output,
                    workflow_status=workflow_status,
                    error_code=error_code,
                    error_message=error_message,
                )

                for event_name, data in self._map_internal_event(
                    raw_event,
                    output,
                ):
                    yield self._build_event(
                        run_id,
                        sequence,
                        event_name,
                        data,
                    )
                    sequence += 1
        except Exception:  # noqa: BLE001 - public protocol must close with done.
            yield self._build_event(
                run_id,
                sequence,
                "done",
                {
                    "status": "failed",
                    "error_code": error_code or "GRAPH_STREAM_FAILED",
                    "error_message": error_message or "工单图事件流执行失败。",
                },
            )
            return

        if workflow_status == "failed":
            done_data: dict[str, object] = {
                "status": "failed",
                "error_code": error_code or "GRAPH_EXECUTION_FAILED",
                "error_message": error_message or "工单流程执行失败。",
            }
        elif workflow_status == "rejected":
            done_data = {"status": "rejected"}
        else:
            done_data = {"status": "completed"}

        yield self._build_event(run_id, sequence, "done", done_data)

    def _build_event(
        self,
        run_id: str,
        sequence: int,
        event_name: AgentEventName,
        data: dict[str, object],
    ) -> AgentEvent:
        occurred_at = self._clock()
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        else:
            occurred_at = occurred_at.astimezone(timezone.utc)
        return AgentEvent(
            run_id=run_id,
            sequence=sequence,
            event=event_name,
            occurred_at=occurred_at,
            data=data,
        )

    def _map_internal_event(
        self,
        raw_event: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> list[tuple[AgentEventName, dict[str, object]]]:
        event_name = raw_event.get("event")
        node_name = raw_event.get("name")
        stage = NODE_STAGE_BY_NAME.get(node_name)

        if event_name == "on_chain_start" and stage is not None:
            return [("status", {"stage": stage, "state": "started"})]

        if event_name == "on_chain_end" and stage is not None:
            node_state = (
                "failed" if output.get("status") == "failed" else "completed"
            )
            mapped: list[tuple[AgentEventName, dict[str, object]]] = [
                ("status", {"stage": stage, "state": node_state})
            ]
            if node_name == "retrieve_policy_stub":
                retrieval = self._retrieval_payload(output)
                if retrieval is not None:
                    mapped.append(("retrieval", retrieval))
            elif node_name in {"build_clarification", "draft_response"}:
                text = output.get("draft_response")
                if isinstance(text, str) and text.strip():
                    mapped.append(("text", {"text": text.strip()}))
            elif node_name == "assess_risk":
                approval = self._approval_payload(output)
                if approval is not None:
                    mapped.append(("approval_required", approval))
            return mapped

        if event_name == "on_chat_model_end":
            return [("context_usage", self._context_usage_payload(raw_event))]

        return []

    @staticmethod
    def _chain_output(raw_event: Mapping[str, Any]) -> dict[str, Any]:
        data = raw_event.get("data")
        if not isinstance(data, Mapping):
            return {}
        output = data.get("output")
        if not isinstance(output, Mapping):
            return {}
        return dict(output)

    @staticmethod
    def _capture_workflow_result(
        output: Mapping[str, Any],
        *,
        workflow_status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> tuple[str, str | None, str | None]:
        status = output.get("status")
        if status == "failed":
            workflow_status = "failed"
        elif status == "rejected" and workflow_status != "failed":
            workflow_status = "rejected"
        elif status == "completed" and workflow_status != "failed":
            workflow_status = "completed"

        next_error_code = output.get("error_code")
        if isinstance(next_error_code, str) and next_error_code:
            error_code = next_error_code
        next_error_message = output.get("error_message")
        if isinstance(next_error_message, str) and next_error_message:
            error_message = next_error_message
        return workflow_status, error_code, error_message

    @staticmethod
    def _retrieval_payload(output: Mapping[str, Any]) -> dict[str, object] | None:
        raw_refs = output.get("evidence_refs")
        if not isinstance(raw_refs, list):
            return None

        evidence: list[dict[str, str]] = []
        for raw_ref in raw_refs:
            if isinstance(raw_ref, Mapping):
                source_id = raw_ref.get("source_id")
                title = raw_ref.get("title")
                snippet = raw_ref.get("snippet")
            else:
                source_id = getattr(raw_ref, "source_id", None)
                title = getattr(raw_ref, "title", None)
                snippet = getattr(raw_ref, "snippet", None)
            if not isinstance(source_id, str) or not source_id:
                continue
            item: dict[str, str] = {"source_id": source_id}
            if isinstance(title, str) and title:
                item["title"] = title
            if isinstance(snippet, str) and snippet:
                item["snippet"] = snippet
            evidence.append(item)

        return {"evidence_refs": evidence, "count": len(evidence)}

    @staticmethod
    def _approval_payload(
        output: Mapping[str, Any],
    ) -> dict[str, object] | None:
        if output.get("requires_approval") is not True:
            return None
        reasons = output.get("risk_reasons")
        safe_reasons = (
            [reason for reason in reasons if isinstance(reason, str)]
            if isinstance(reasons, list)
            else []
        )
        return {
            "risk_level": output.get("risk_level", "high"),
            "risk_reasons": safe_reasons,
            "requires_approval": True,
        }

    @classmethod
    def _context_usage_payload(
        cls,
        raw_event: Mapping[str, Any],
    ) -> dict[str, object]:
        usage = cls._find_usage(raw_event)
        context_tokens = cls._number(usage.get("total_tokens"))
        context_window_tokens = cls._number(usage.get("context_window_tokens"))
        percent = (
            round(context_tokens / context_window_tokens * 100, 2)
            if context_tokens is not None
            and context_window_tokens is not None
            and context_window_tokens > 0
            else None
        )
        payload: dict[str, object] = {
            "context_tokens": context_tokens,
            "context_window_tokens": context_window_tokens,
            "context_usage_percent": percent,
            "available": context_tokens is not None,
        }
        for source_key in ("input_tokens", "output_tokens", "total_tokens"):
            value = cls._number(usage.get(source_key))
            if value is not None:
                payload[source_key] = value

        stage = cls._stage_from_metadata(raw_event)
        if stage is not None:
            payload["stage"] = stage
        return payload

    @staticmethod
    def _find_usage(raw_event: Mapping[str, Any]) -> Mapping[str, Any]:
        data = raw_event.get("data")
        output: Any = data.get("output") if isinstance(data, Mapping) else None

        candidates: list[Any] = [output]
        if isinstance(output, Mapping):
            candidates.extend(
                [
                    output.get("usage_metadata"),
                    output.get("response_metadata"),
                    output.get("usage"),
                ]
            )
            response_metadata = output.get("response_metadata")
            if isinstance(response_metadata, Mapping):
                candidates.append(response_metadata.get("token_usage"))
        else:
            candidates.extend(
                [
                    getattr(output, "usage_metadata", None),
                    getattr(output, "response_metadata", None),
                ]
            )
            response_metadata = getattr(output, "response_metadata", None)
            if isinstance(response_metadata, Mapping):
                candidates.append(response_metadata.get("token_usage"))

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            if any(
                key in candidate
                for key in ("total_tokens", "input_tokens", "output_tokens")
            ):
                return candidate
        return {}

    @staticmethod
    def _stage_from_metadata(raw_event: Mapping[str, Any]) -> str | None:
        metadata = raw_event.get("metadata")
        if not isinstance(metadata, Mapping):
            return None
        node_name = metadata.get("langgraph_node")
        return NODE_STAGE_BY_NAME.get(node_name)

    @staticmethod
    def _number(value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value
