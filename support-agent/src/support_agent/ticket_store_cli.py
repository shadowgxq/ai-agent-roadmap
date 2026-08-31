"""Offline W15 experiment for thread checkpoints and cross-thread Store data."""

import json
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore


PreferenceOperation = Literal["write", "read"]
PREFERENCE_KEY = "preferences"


@dataclass(frozen=True)
class PreferenceContext:
    """Stable tenant and user identity supplied to one graph run."""

    organization_id: str
    user_id: str


class PreferenceState(TypedDict):
    """Small per-thread state used only by the Store scope experiment."""

    operation: PreferenceOperation
    language: NotRequired[str]
    observed_language: NotRequired[str | None]


def preference_namespace(context: PreferenceContext) -> tuple[str, ...]:
    """Keep one user's preferences isolated inside an organization."""

    return (
        "organizations",
        context.organization_id,
        "users",
        context.user_id,
    )


def preference_node(
    state: PreferenceState,
    runtime: Runtime[PreferenceContext],
) -> dict[str, object]:
    """Write or read a preference through the Store injected by LangGraph."""

    store = runtime.store
    if store is None:
        raise RuntimeError("偏好实验没有注入 LangGraph Store。")

    namespace = preference_namespace(runtime.context)
    if state["operation"] == "write":
        language = state.get("language", "").strip()
        if not language:
            raise ValueError("写入偏好时 language 不能为空。")
        store.put(
            namespace,
            PREFERENCE_KEY,
            {"language": language},
        )
        return {"observed_language": language}

    item = store.get(namespace, PREFERENCE_KEY)
    language = item.value.get("language") if item is not None else None
    return {
        "observed_language": language if isinstance(language, str) else None,
    }


def create_preference_graph(
    *,
    store: BaseStore,
    checkpointer: InMemorySaver,
):
    """Build a one-node graph with separate thread state and shared Store data."""

    builder = StateGraph(
        state_schema=PreferenceState,
        context_schema=PreferenceContext,
    )
    builder.add_node("preferences", preference_node)
    builder.add_edge(START, "preferences")
    builder.add_edge("preferences", END)
    return builder.compile(
        checkpointer=checkpointer,
        store=store,
    )


def _thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def run_store_demo() -> dict[str, object]:
    """Show shared user memory without sharing either thread checkpoint."""

    organization_id = "org_w15_store_demo"
    user_id = "user_123"
    other_user_id = "user_456"
    thread_a = f"thread_a_{uuid4().hex}"
    thread_b = f"thread_b_{uuid4().hex}"
    thread_other_user = f"thread_other_{uuid4().hex}"
    thread_fresh_store = f"thread_fresh_{uuid4().hex}"

    store = InMemoryStore()
    checkpointer = InMemorySaver()
    graph = create_preference_graph(
        store=store,
        checkpointer=checkpointer,
    )
    user_context = PreferenceContext(
        organization_id=organization_id,
        user_id=user_id,
    )

    graph.invoke(
        {"operation": "write", "language": "zh"},
        config=_thread_config(thread_a),
        context=user_context,
    )
    thread_b_result = graph.invoke(
        {"operation": "read"},
        config=_thread_config(thread_b),
        context=user_context,
    )
    other_user_result = graph.invoke(
        {"operation": "read"},
        config=_thread_config(thread_other_user),
        context=PreferenceContext(
            organization_id=organization_id,
            user_id=other_user_id,
        ),
    )

    thread_a_snapshot = graph.get_state(_thread_config(thread_a))
    thread_b_snapshot = graph.get_state(_thread_config(thread_b))

    fresh_store = InMemoryStore()
    fresh_graph = create_preference_graph(
        store=fresh_store,
        checkpointer=InMemorySaver(),
    )
    fresh_store_result = fresh_graph.invoke(
        {"operation": "read"},
        config=_thread_config(thread_fresh_store),
        context=user_context,
    )

    checks = {
        "thread_ids_are_different": thread_a != thread_b,
        "thread_checkpoints_are_separate": (
            thread_a_snapshot.values.get("operation") == "write"
            and thread_b_snapshot.values.get("operation") == "read"
        ),
        "same_user_memory_crosses_threads": (
            thread_b_result.get("observed_language") == "zh"
        ),
        "other_user_is_isolated": (
            other_user_result.get("observed_language") is None
        ),
        "fresh_store_has_no_memory": (
            fresh_store_result.get("observed_language") is None
        ),
    }
    return {
        "store_type": type(store).__name__,
        "checkpointer_type": type(checkpointer).__name__,
        "namespace": list(preference_namespace(user_context)),
        "thread_a": thread_a,
        "thread_b": thread_b,
        "thread_a_checkpoint": dict(thread_a_snapshot.values),
        "thread_b_checkpoint": dict(thread_b_snapshot.values),
        "thread_b_language": thread_b_result.get("observed_language"),
        "other_user_language": other_user_result.get("observed_language"),
        "fresh_store_language": fresh_store_result.get("observed_language"),
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> int:
    payload = run_store_demo()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
