"""Manage one active Agent run and stream its ordered events."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..agent.config import AgentSettings
from ..agent.loop import AgentEventName
from ..agent.runtime import run_coding_agent
from .events import AgentEvent, EventType, is_public_event


@dataclass
class RunState:
    run_id: str
    task: str
    events: list[AgentEvent] = field(default_factory=list)
    queue: asyncio.Queue[AgentEvent] = field(default_factory=asyncio.Queue)
    status: str = "running"
    finished: bool = False


class RunManager:
    """Keep a small in-memory run registry for the single-page viewer."""

    def __init__(
        self,
        *,
        workdir: Path,
        settings: AgentSettings | None = None,
    ) -> None:
        self.workdir = workdir.resolve()
        self.settings = settings
        self._runs: dict[str, RunState] = {}

    async def start(self, task: str) -> RunState:
        """Create a run and schedule it without blocking the HTTP request."""
        task = task.strip()
        if not task:
            raise ValueError("task 不能为空")
        if any(not state.finished for state in self._runs.values()):
            raise RuntimeError("当前 mini viewer 一次只允许一个运行中的任务")

        state = RunState(run_id=uuid4().hex, task=task)
        self._runs[state.run_id] = state
        asyncio.create_task(
            self._execute(state),
            name=f"agent-{state.run_id}",
        )
        return state

    def get(self, run_id: str) -> RunState:
        """Return a run or raise KeyError for the HTTP layer to translate."""
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"run 不存在: {run_id}") from exc

    async def stream(self, run_id: str) -> AsyncIterator[str]:
        """Replay stored events, then wait for new events from the queue."""
        state = self.get(run_id)
        cursor = 0
        while True:
            while cursor < len(state.events):
                event = state.events[cursor]
                cursor += 1
                yield event.to_sse()

            if state.finished:
                break

            await state.queue.get()

    async def _publish(
        self,
        state: RunState,
        event: EventType,
        data: dict[str, Any],
    ) -> None:
        item = AgentEvent(
            sequence=len(state.events),
            run_id=state.run_id,
            event=event,
            data=data,
        )
        state.events.append(item)
        if event == "done":
            state.status = str(data.get("status", "completed"))
            state.finished = True
        await state.queue.put(item)

    async def _execute(self, state: RunState) -> None:
        async def publish(
            event: AgentEventName,
            data: dict[str, Any],
        ) -> None:
            # Agent Loop 还可以产生内部观测事件；Web 只发布冻结范围内
            # 的公共事件，不能用 cast 把任意事件强行伪装成 SSE 协议。
            if not is_public_event(event):
                return
            await self._publish(state, event, data)

        try:
            await run_coding_agent(
                task=state.task,
                workdir=self.workdir,
                settings=self.settings or AgentSettings(),
                run_id=state.run_id,
                checkpoint_enabled=True,
                event_callback=publish,
            )
        except asyncio.CancelledError:
            state.status = "interrupted"
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {"status": "interrupted"},
                )
            raise
        except Exception as exc:
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {"status": "failed", "error": str(exc)},
                )
