from __future__ import annotations
from pricing import calc_cost

import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parent.parent / "shared"))

from agent_sdk import get_async_client, load_config  # noqa: E402


config = load_config()

app = FastAPI()


@dataclass
class SessionState:
    history: list[dict[str, str]] = field(default_factory=list)
    cumulative_cost_usd: float = 0.0


conversation_store: dict[str, SessionState] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    model = config.model
    system_prompt = "你是一条佛系的鱼"
    session_id = body.session_id or str(uuid.uuid4())
    session = conversation_store.setdefault(session_id, SessionState())
    history = session.history
    messages = [
        *history,
        {"role": "user", "content": body.message},
    ]

    client = get_async_client(config)

    async def event_stream():
        async with client.messages.stream(
            model=model,
            system=system_prompt,
            messages=messages,
            max_tokens=2000,
        ) as stream:
            async for text in stream.text_stream:
                payload = {"type": "text_delta", "text": text}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            final_message = await stream.get_final_message()
            assistant_text_parts: list[str] = []
            for block in final_message.content:
                if block.type == "text":
                    assistant_text_parts.append(block.text)

            history.append({"role": "user", "content": body.message})
            history.append(
                {"role": "assistant", "content": "".join(assistant_text_parts)}
            )
            input_tokens = getattr(final_message.usage, "input_tokens", None)
            output_tokens = getattr(final_message.usage, "output_tokens", None)
            cache_read_input_tokens = getattr(
                final_message.usage, "cache_read_input_tokens", None
            )
            total_input_tokens = (input_tokens or 0) + (
                cache_read_input_tokens or 0
            )
            round_cost_usd = calc_cost(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            )
            session.cumulative_cost_usd += round_cost_usd
            payload = {
                "type": "message_stop",
                "session_id": session_id,
                "model": model,
                "stop_reason": final_message.stop_reason,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cache_read_input_tokens,
                    "total_input_tokens": total_input_tokens,
                },
                "round_cost_usd": round_cost_usd,
                "cumulative_cost_usd": session.cumulative_cost_usd,
                "history_length": len(history),
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
