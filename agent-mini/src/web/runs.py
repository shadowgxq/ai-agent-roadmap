"""Manage Sessions, Runs, Messages, and ordered Agent events."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..agent.config import AgentSettings
from ..agent.loop import AgentEventName, MaxTurnsExceeded
from ..agent.runtime import run_coding_agent
from ..execution.repository import Repository
from .events import AgentEvent, EventType, to_public_event
from .models import (
    Message,
    MessageKind,
    MessageRole,
    Run,
    RunStatus,
    Session,
    SessionDetail,
    utc_now,
)


AgentRunner = Callable[..., Awaitable[Any]]


@dataclass
class RunState:
    """运行时状态；API 领域模型通过 ``to_model`` 暴露。"""

    run_id: str
    session_id: str
    message_id: str
    task: str
    created_at: datetime
    events: list[AgentEvent] = field(default_factory=list)
    queue: asyncio.Queue[AgentEvent] = field(default_factory=asyncio.Queue)
    status: RunStatus = "queued"
    finished: bool = False
    finished_at: datetime | None = None
    pending_tool_use_ids: set[str] = field(default_factory=set)
    execution_task: asyncio.Task[None] | None = None
    cancel_requested: bool = False
    pending_confirmation: "ConfirmationState | None" = None

    def to_model(self) -> Run:
        """把可变运行状态转换为 API/历史使用的 Run 模型。"""
        return Run(
            run_id=self.run_id,
            session_id=self.session_id,
            message_id=self.message_id,
            task=self.task,
            status=self.status,
            created_at=self.created_at,
            finished_at=self.finished_at,
            confirmation_id=(
                self.pending_confirmation.confirmation_id
                if self.pending_confirmation is not None
                else None
            ),
            confirmation_command=(
                self.pending_confirmation.command
                if self.pending_confirmation is not None
                else None
            ),
            confirmation_reason=(
                self.pending_confirmation.reason
                if self.pending_confirmation is not None
                else None
            ),
        )


@dataclass
class ConfirmationState:
    """一次等待用户批准的 Shell 命令。"""

    confirmation_id: str
    command: str
    reason: str
    future: asyncio.Future[bool]


class RunManager:
    """在内存中管理 Session、Run 和 Message，不引入数据库。"""

    def __init__(
        self,
        *,
        workdir: Path,
        settings: AgentSettings | None = None,
        runner: AgentRunner | None = None,
        repository_isolation: bool = False,
    ) -> None:
        self.workdir = workdir.resolve()
        self.settings = settings
        # Demo/宿主可以打开 Git 临时 Worktree；默认保持 W11 的本地目录行为，便于测试注入。
        self.repository = (
            Repository.discover(self.workdir) if repository_isolation else None
        )
        # 生产环境使用真实 Runtime；测试可注入 fake runner，隔离 LLM、工具和外部服务。
        self.runner = runner if runner is not None else run_coding_agent
        # Session/Message 保存可查询历史；RunState 另外保存 SSE 回放和队列所需的可变运行态。
        self._sessions: dict[str, Session] = {}
        self._messages: dict[str, Message] = {}
        self._runs: dict[str, RunState] = {}

    def create_session(self) -> Session:
        """创建一个独立的对话容器。"""
        session = Session(session_id=uuid4().hex)
        self._sessions[session.session_id] = session
        return session.model_copy(deep=True)

    def list_sessions(self) -> list[Session]:
        """返回按最近更新时间倒序排列的 Session 摘要。"""
        return [
            session.model_copy(deep=True)
            for session in sorted(
                self._sessions.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
        ]

    def get_session(self, session_id: str) -> Session:
        """返回 Session；不存在时交给 HTTP 层转换为 404。"""
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"session 不存在: {session_id}") from exc

    def get_session_detail(self, session_id: str) -> SessionDetail:
        """组装一个 Session 及其关联 Runs、Messages。"""
        session = self.get_session(session_id)
        runs = [
            state.to_model()
            for state in self._runs.values()
            if state.session_id == session_id
        ]
        messages = [
            message.model_copy(deep=True)
            for message in self._messages.values()
            if message.session_id == session_id
        ]
        return SessionDetail(
            session=session.model_copy(deep=True),
            runs=sorted(runs, key=lambda item: item.created_at),
            messages=sorted(messages, key=lambda item: item.created_at),
        )

    async def start(
        self,
        task: str,
        *,
        session_id: str | None = None,
    ) -> RunState:
        """为 Session 创建一次 Run，并异步启动唯一 Agent Loop。"""
        task = task.strip()
        # 统一去掉边界空白后再写入消息和 Runtime，避免同一任务出现两个文本表示。
        if not task:
            raise ValueError("task 不能为空")

        session = self.get_session(session_id) if session_id else None
        # 当前 Manager 共享一组内存队列和状态，因此在单实例内只允许一个未结束 Run。
        if any(not state.finished for state in self._runs.values()):
            raise RuntimeError("当前运行器一次只允许一个运行中的任务")

        if session is None:
            # 兼容旧的 POST /runs：没有 session_id 时自动创建 Session。
            session = self._create_session()

        run_id = uuid4().hex
        message_id = uuid4().hex
        # 先记录用户消息，再建立 Run 引用，保证详情页能从 Run 追溯触发它的原始输入。
        self._add_message(
            message_id=message_id,
            session_id=session.session_id,
            run_id=run_id,
            role="user",
            kind="text",
            content=task,
        )
        state = RunState(
            run_id=run_id,
            session_id=session.session_id,
            message_id=message_id,
            task=task,
            created_at=utc_now(),
        )
        self._runs[state.run_id] = state
        # 先把 queued 作为首个可回放状态发布，再由后台协程切换到 running。
        await self._publish(state, "status", {"status": "queued"})
        state.execution_task = asyncio.create_task(
            self._execute(state),
            name=f"agent-{state.run_id}",
        )
        return state

    def get(self, run_id: str) -> RunState:
        """返回 Run；不存在时交给 HTTP 层转换为 404。"""
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"run 不存在: {run_id}") from exc

    def get_active_run(self) -> Run | None:
        """返回当前唯一未结束的 Run，供刷新页面或冲突恢复使用。"""
        for state in reversed(list(self._runs.values())):
            if not state.finished:
                return state.to_model()
        return None

    async def confirm(self, run_id: str, approved: bool) -> RunState:
        """完成当前等待中的命令确认。"""
        state = self.get(run_id)
        confirmation = state.pending_confirmation
        if confirmation is None or state.status != "waiting_confirmation":
            raise ValueError("当前 Run 没有等待确认的命令")
        if not confirmation.future.done():
            confirmation.future.set_result(approved)
        return state

    async def cancel(self, run_id: str) -> RunState:
        """请求取消 Run，并保证最终通过 cancelled done 收束。"""
        state = self.get(run_id)
        if state.finished:
            return state

        state.cancel_requested = True
        if state.pending_confirmation is not None:
            future = state.pending_confirmation.future
            if not future.done():
                future.set_result(False)

        task = state.execution_task
        if state.status == "queued" and not state.finished:
            await self._publish(
                state,
                "done",
                {"status": "cancelled"},
            )
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # 取消语义已经由 _execute 转成 cancelled done；这里等待清理完成后再返回 API。
                pass
        return state

    async def stream(self, run_id: str) -> AsyncIterator[str]:
        """先回放已保存事件，再等待队列中的新事件。"""
        state = self.get(run_id)
        # cursor 只属于当前连接；events 是权威历史，queue 只负责在没有新事件时唤醒连接。
        cursor = 0
        while True:
            while cursor < len(state.events):
                event = state.events[cursor]
                cursor += 1
                yield event.to_sse()

            if state.finished:
                break

            # 消费队列中的唤醒信号后重新检查 events，避免新连接遗漏已发布事件。
            await state.queue.get()

    def _create_session(self) -> Session:
        """创建并返回内部可变 Session 实例。"""
        session = Session(session_id=uuid4().hex)
        self._sessions[session.session_id] = session
        return session

    def _touch_session(self, session_id: str) -> None:
        self._sessions[session_id].updated_at = utc_now()

    def _add_message(
        self,
        *,
        message_id: str,
        session_id: str,
        run_id: str,
        role: MessageRole,
        kind: MessageKind,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        message = Message(
            message_id=message_id,
            session_id=session_id,
            run_id=run_id,
            role=role,
            kind=kind,
            content=content,
            metadata=metadata or {},
        )
        self._messages[message.message_id] = message
        self._touch_session(session_id)
        return message

    def _record_event_message(
        self,
        state: RunState,
        event: EventType,
        data: dict[str, Any],
    ) -> None:
        """把公共事件压缩成可查询的 Message，不替代模型 Context。"""
        # 历史只保存用户可查看的文本和工具交互；context_usage、done 留在事件流中即可。
        if event == "text":
            content = data.get("text")
            if not isinstance(content, str) or not content:
                return
            role: MessageRole = "assistant"
            kind: MessageKind = "text"
        elif event == "tool_call":
            content = json.dumps(
                data.get("calls", []),
                ensure_ascii=False,
                default=str,
            )
            role = "assistant"
            kind = "tool_call"
        elif event == "tool_result":
            content = json.dumps(
                data.get("results", []),
                ensure_ascii=False,
                default=str,
            )
            role = "tool"
            kind = "tool_result"
        elif event == "diff":
            content = json.dumps(
                data.get("files", []),
                ensure_ascii=False,
                default=str,
            )
            role = "assistant"
            kind = "diff"
        else:
            return

        turn = data.get("turn")
        metadata = {"turn": turn} if isinstance(turn, int) else {}
        self._add_message(
            message_id=uuid4().hex,
            session_id=state.session_id,
            run_id=state.run_id,
            role=role,
            kind=kind,
            content=content,
            metadata=metadata,
        )

    async def _publish(
        self,
        state: RunState,
        event: EventType,
        data: dict[str, Any],
    ) -> None:
        if state.finished:
            raise RuntimeError(f"run {state.run_id} 已结束，不能继续发布事件")
        # 先完成协议与 tool pairing 校验，再写入历史并入队，避免消费者看到半成品事件。
        item = AgentEvent(
            sequence=len(state.events),
            run_id=state.run_id,
            event=event,
            data=data,
        )
        self._update_tool_pairing(state, item)
        self._record_event_message(state, item.event, item.data)
        state.events.append(item)
        if event == "status":
            state.status = item.data["status"]
        if event == "done":
            # done 是唯一终态；标记 finished 后，stream 会在发完最后一个事件时自然退出。
            status = item.data["status"]
            state.status = (
                status
                if status in {
                    "completed",
                    "failed",
                    "max_turns",
                    "cancelled",
                }
                else "failed"
            )
            state.finished = True
            state.finished_at = utc_now()
        self._touch_session(state.session_id)
        await state.queue.put(item)

    def _update_tool_pairing(
        self,
        state: RunState,
        event: AgentEvent,
    ) -> None:
        """校验 tool_call/tool_result 的 tool_use_id 生命周期。"""
        if event.event == "tool_call":
            # 同一批次和跨批次都不能复用 ID；pending 集合代表仍等待结果的调用。
            tool_use_ids = {
                str(call["tool_use_id"])
                for call in event.data["calls"]
            }
            if len(tool_use_ids) != len(event.data["calls"]):
                raise ValueError("同一个 tool_call 事件包含重复 tool_use_id")
            duplicates = tool_use_ids & state.pending_tool_use_ids
            if duplicates:
                raise ValueError(
                    f"tool_use_id 已处于等待结果状态: {sorted(duplicates)}"
                )
            state.pending_tool_use_ids.update(tool_use_ids)
            return

        if event.event == "tool_result":
            # 结果必须引用 pending 调用；校验通过后才移除，避免失败结果破坏后续配对。
            tool_use_ids = {
                str(result["tool_use_id"])
                for result in event.data["results"]
            }
            if len(tool_use_ids) != len(event.data["results"]):
                raise ValueError("同一个 tool_result 事件包含重复 tool_use_id")
            unknown_ids = tool_use_ids - state.pending_tool_use_ids
            if unknown_ids:
                raise ValueError(
                    f"tool_result 没有匹配的 tool_call: {sorted(unknown_ids)}"
                )
            state.pending_tool_use_ids.difference_update(tool_use_ids)
            return

        # 只有正常结束状态要求所有工具调用都已闭合；失败或取消可能发生在工具返回之前。
        if (
            event.event == "done"
            and event.data["status"] in {"completed", "max_turns"}
            and state.pending_tool_use_ids
        ):
            raise ValueError(
                "Run 正常结束时仍有未配对的 tool_use_id: "
                f"{sorted(state.pending_tool_use_ids)}"
            )

    async def _execute(self, state: RunState) -> None:
        """桥接 Agent Runtime 与 Web Adapter，并把异常统一收束为终态事件。"""
        if state.cancel_requested:
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {"status": "cancelled"},
                )
            return

        await self._publish(state, "status", {"status": "running"})

        async def publish(
            event: AgentEventName,
            data: dict[str, Any],
        ) -> None:
            # Runtime 的内部事件在进入历史和 SSE 之前过滤，Web 层只接收公开协议类型。
            event_type = to_public_event(event)
            if event_type is None:
                return
            await self._publish(state, event_type, data)

        async def request_confirmation(command: str, reason: str) -> bool:
            """暂停 Runtime，等待 Web/CLI Adapter 通过 Manager 回答。"""
            if state.cancel_requested or state.finished:
                return False
            loop = asyncio.get_running_loop()
            confirmation = ConfirmationState(
                confirmation_id=uuid4().hex,
                command=command,
                reason=reason,
                future=loop.create_future(),
            )
            state.pending_confirmation = confirmation
            await self._publish(
                state,
                "status",
                {
                    "status": "waiting_confirmation",
                    "message": "命令等待用户确认",
                    "confirmation_id": confirmation.confirmation_id,
                    "command": command,
                    "reason": reason,
                },
            )
            try:
                return await confirmation.future
            finally:
                if state.pending_confirmation is confirmation:
                    state.pending_confirmation = None
                if not state.finished and not state.cancel_requested:
                    await self._publish(
                        state,
                        "status",
                        {"status": "running"},
                    )

        async def execute_runner() -> None:
            runner_kwargs = {
                "task": state.task,
                "settings": self.settings or AgentSettings(),
                "run_id": state.run_id,
                "session_id": state.session_id,
                "message_id": state.message_id,
                "checkpoint_enabled": True,
                "event_callback": publish,
                "on_confirm": request_confirmation,
            }
            if self.repository is None:
                await self.runner(
                    workdir=self.workdir,
                    **runner_kwargs,
                )
                return

            # Worktree 的打开、运行和清理必须在同一生命周期内，避免 Sandbox 挂载已被删除的目录。
            with self.repository.open_workspace() as workspace:
                await self.runner(
                    workdir=workspace.root,
                    workspace=workspace,
                    **runner_kwargs,
                )

        try:
            await execute_runner()
        except MaxTurnsExceeded as exc:
            # Runtime 用异常跳出循环时，仍转换成前端可消费的标准 done 事件。
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {
                        "status": "max_turns",
                        "turn": exc.stats.turns,
                        "max_turns": exc.max_turns,
                    },
                )
        except asyncio.CancelledError:
            # 先发布 cancelled 让前端收束，再重新抛出以保留 asyncio 的取消语义。
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {"status": "cancelled"},
                )
            raise
        except Exception as exc:
            # 未处理异常也转成 failed 终态，避免 SSE 客户端永久等待 done。
            if not state.finished:
                await self._publish(
                    state,
                    "done",
                    {"status": "failed", "error": str(exc)},
                )
