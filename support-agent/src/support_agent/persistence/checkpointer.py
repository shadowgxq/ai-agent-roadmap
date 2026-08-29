"""PostgreSQL checkpointer lifecycle for W15 durable execution."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


@asynccontextmanager
async def create_checkpointer(
    database_url: str,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open and initialize the checkpointer for one application lifecycle."""

    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        # W15 keeps setup close to the demo lifecycle. A production service would
        # normally run this once during deployment or application startup.
        await checkpointer.setup()
        yield checkpointer
