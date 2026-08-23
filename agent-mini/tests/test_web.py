"""Web Adapter 的 FastAPI、SSE 和 Runner 注入测试。"""

import asyncio
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.agent.config import AgentSettings
from src.web.app import create_app
from src.web.runs import RunManager


def make_test_settings() -> AgentSettings:
    """创建不会读取本地凭证的测试配置。"""
    return AgentSettings(_env_file=None, api_key="test-key")


async def emit_conversation(**kwargs: Any) -> None:
    """模拟一轮包含文本、工具调用、工具结果和终态的 Agent。"""
    callback = kwargs["event_callback"]
    await callback("text", {"turn": 1, "text": "准备读取文件"})
    await callback(
        "tool_call",
        {
            "turn": 1,
            "calls": [
                {
                    "tool_use_id": "call-1",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                }
            ],
        },
    )
    await callback(
        "tool_result",
        {
            "turn": 1,
            "results": [
                {
                    "tool_use_id": "call-1",
                    "content": "README 内容",
                    "is_error": False,
                }
            ],
        },
    )
    await callback(
        "diff",
        {
            "turn": 1,
            "files": [
                {
                    "path": "README.md",
                    "status": "modified",
                    "patch": "--- a/README.md\n+++ b/README.md",
                    "additions": 1,
                    "deletions": 1,
                    "binary": False,
                    "truncated": False,
                }
            ],
        },
    )
    await callback(
        "done",
        {
            "status": "completed",
            "turn": 1,
            "finish_reason": "fake_runner",
        },
    )


def read_sse_payloads(body: str) -> list[dict[str, Any]]:
    """提取 SSE data 行，验证测试关注的公共事件信封。"""
    payloads: list[dict[str, Any]] = []
    for block in body.strip().split("\n\n"):
        data_line = next(
            line for line in block.splitlines() if line.startswith("data: ")
        )
        payloads.append(json.loads(data_line.removeprefix("data: ")))
    return payloads


def test_session_run_and_sse_stream(tmp_path) -> None:
    app = create_app(
        workdir=tmp_path,
        settings=make_test_settings(),
        runner=emit_conversation,
    )

    with TestClient(app) as client:
        session_response = client.post("/sessions")
        assert session_response.status_code == 201
        session_id = session_response.json()["session_id"]

        run_response = client.post(
            f"/sessions/{session_id}/runs",
            json={"task": "读取 README"},
        )
        assert run_response.status_code == 202
        run = run_response.json()
        assert run["session_id"] == session_id
        assert run["run_id"]
        assert run["message_id"]

        stream_response = client.get(f"/runs/{run['run_id']}/events")
        assert stream_response.status_code == 200
        assert stream_response.headers["content-type"].startswith(
            "text/event-stream"
        )

        events = read_sse_payloads(stream_response.text)
        assert [event["event"] for event in events] == [
            "status",
            "status",
            "text",
            "tool_call",
            "tool_result",
            "diff",
            "done",
        ]
        assert [event["sequence"] for event in events] == [0, 1, 2, 3, 4, 5, 6]
        assert [event["data"]["status"] for event in events[:2]] == [
            "queued",
            "running",
        ]
        assert events[3]["data"]["calls"][0]["tool_use_id"] == "call-1"
        assert events[4]["data"]["results"][0]["tool_use_id"] == "call-1"
        assert events[5]["data"]["files"][0]["path"] == "README.md"
        assert events[-1]["data"]["status"] == "completed"

        detail = client.get(f"/sessions/{session_id}").json()
        assert [message["kind"] for message in detail["messages"]] == [
            "text",
            "text",
            "tool_call",
            "tool_result",
            "diff",
        ]
        assert detail["runs"][0]["status"] == "completed"


def test_active_run_endpoint_reports_structured_conflict(tmp_path) -> None:
    async def delayed_runner(**kwargs: Any) -> None:
        callback = kwargs["event_callback"]
        await callback("text", {"turn": 1, "text": "运行中"})
        await asyncio.sleep(0.2)
        await callback("done", {"status": "completed", "turn": 1})

    app = create_app(
        workdir=tmp_path,
        settings=make_test_settings(),
        runner=delayed_runner,
    )

    with TestClient(app) as client:
        session_id = client.post("/sessions").json()["session_id"]
        first_run = client.post(
            f"/sessions/{session_id}/runs",
            json={"task": "保持运行"},
        ).json()

        active_response = client.get("/runs/active")
        assert active_response.status_code == 200
        active_run = active_response.json()
        assert active_run["run_id"] == first_run["run_id"]
        assert active_run["status"] in {"queued", "running"}

        conflict_response = client.post(
            f"/sessions/{session_id}/runs",
            json={"task": "重复提交"},
        )
        assert conflict_response.status_code == 409
        assert conflict_response.json()["detail"] == {
            "code": "active_run",
            "message": "当前运行器一次只允许一个运行中的任务",
            "active_run_id": first_run["run_id"],
            "session_id": session_id,
            "status": active_run["status"],
        }


def test_runner_failure_becomes_failed_done_event(tmp_path) -> None:
    async def failing_runner(**kwargs: Any) -> None:
        raise RuntimeError("fake runner failed")

    app = create_app(
        workdir=tmp_path,
        settings=make_test_settings(),
        runner=failing_runner,
    )

    with TestClient(app) as client:
        run_response = client.post("/runs", json={"task": "触发失败"})
        assert run_response.status_code == 202

        stream_response = client.get(
            f"/runs/{run_response.json()['run_id']}/events"
        )
        events = read_sse_payloads(stream_response.text)

        assert [event["event"] for event in events] == ["status", "status", "done"]
        assert events[-1]["data"] == {
            "status": "failed",
            "turn": None,
            "finish_reason": None,
            "error": "fake runner failed",
            "max_turns": None,
        }


def test_run_manager_stream_waits_for_live_events(tmp_path) -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        async def delayed_runner(**kwargs: Any) -> None:
            callback = kwargs["event_callback"]
            await callback("text", {"turn": 1, "text": "实时事件"})
            await release.wait()
            await callback("done", {"status": "completed", "turn": 1})

        manager = RunManager(
            workdir=tmp_path,
            settings=make_test_settings(),
            runner=delayed_runner,
        )
        state = await manager.start("等待实时事件")
        stream = manager.stream(state.run_id)

        first = json.loads(
            (await asyncio.wait_for(anext(stream), timeout=1)).split(
                "data: ", 1
            )[1]
        )
        assert first["event"] == "status"
        assert first["data"]["status"] == "queued"
        assert state.finished is False

        second = json.loads(
            (await asyncio.wait_for(anext(stream), timeout=1)).split(
                "data: ", 1
            )[1]
        )
        assert second["event"] == "status"
        assert second["data"]["status"] == "running"

        third = json.loads(
            (await asyncio.wait_for(anext(stream), timeout=1)).split(
                "data: ", 1
            )[1]
        )
        assert third["event"] == "text"

        release.set()
        fourth = json.loads(
            (await asyncio.wait_for(anext(stream), timeout=1)).split(
                "data: ", 1
            )[1]
        )
        assert fourth["event"] == "done"
        assert state.finished is True

        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(scenario())


def wait_for_active_status(client: TestClient, run_id: str, expected: str) -> dict[str, Any]:
    """等待后台 Run 进入指定状态，避免测试依赖调度时序。"""
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        active_run = client.get("/runs/active").json()
        if active_run and active_run["run_id"] == run_id and active_run["status"] == expected:
            return active_run
        time.sleep(0.01)
    raise AssertionError(f"Run 未在限定时间进入状态: {expected}")


def test_confirmation_pauses_run_until_web_approval(tmp_path) -> None:
    async def confirmation_runner(**kwargs: Any) -> None:
        callback = kwargs["event_callback"]
        on_confirm = kwargs["on_confirm"]
        await callback("text", {"turn": 1, "text": "准备执行受保护命令"})
        approved = await on_confirm("git clean -fd", "命令可能删除未跟踪文件")
        await callback(
            "done",
            {
                "status": "completed" if approved else "failed",
                "turn": 1,
                "finish_reason": "confirmation_test",
            },
        )

    app = create_app(
        workdir=tmp_path,
        settings=make_test_settings(),
        runner=confirmation_runner,
    )

    with TestClient(app) as client:
        run = client.post("/runs", json={"task": "请求受保护命令"}).json()
        waiting = wait_for_active_status(client, run["run_id"], "waiting_confirmation")
        assert waiting["confirmation_command"] == "git clean -fd"
        assert waiting["confirmation_reason"] == "命令可能删除未跟踪文件"

        confirmation_response = client.post(
            f"/runs/{run['run_id']}/confirm",
            json={"approved": True},
        )
        assert confirmation_response.status_code == 200

        events = read_sse_payloads(
            client.get(f"/runs/{run['run_id']}/events").text
        )
        assert [event["data"].get("status") for event in events if event["event"] == "status"] == [
            "queued",
            "running",
            "waiting_confirmation",
            "running",
        ]
        assert events[-1]["event"] == "done"


def test_cancel_endpoint_closes_active_run(tmp_path) -> None:
    async def delayed_runner(**kwargs: Any) -> None:
        await kwargs["event_callback"]("text", {"turn": 1, "text": "运行中"})
        await asyncio.Event().wait()

    app = create_app(
        workdir=tmp_path,
        settings=make_test_settings(),
        runner=delayed_runner,
    )

    with TestClient(app) as client:
        run = client.post("/runs", json={"task": "取消任务"}).json()
        wait_for_active_status(client, run["run_id"], "running")

        cancel_response = client.post(f"/runs/{run['run_id']}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
        assert client.get("/runs/active").json() is None

        events = read_sse_payloads(
            client.get(f"/runs/{run['run_id']}/events").text
        )
        assert events[-1]["event"] == "done"
        assert events[-1]["data"]["status"] == "cancelled"
