"""PostgreSQL checkpointer lifecycle for W15 durable execution."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def ticket_serializer() -> JsonPlusSerializer:
    # Explicitly permit the application's evidence DTO, never arbitrary pickle/classes.
    allowed = [("support_agent.models.workflow", "EvidenceRef")]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed, allowed_json_modules=allowed)


@asynccontextmanager
async def create_checkpointer(
    database_url: str,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open and initialize the checkpointer for one application lifecycle."""

    async with AsyncPostgresSaver.from_conn_string(database_url, serde=ticket_serializer()) as checkpointer:
        # W15 keeps setup close to the demo lifecycle. A production service would
        # normally run this once during deployment or application startup.
        await checkpointer.setup()
        yield checkpointer
