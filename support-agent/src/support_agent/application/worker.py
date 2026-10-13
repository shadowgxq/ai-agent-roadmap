"""One leased task attempt; injected engines keep local checks provider-free."""

import asyncio
from psycopg import OperationalError
from .contracts import Identity
from .store import CancelledRun


async def execute_run(store, settings, org: str, run_id: str, generation: int, engine=None):
    run = await store.claim(org, run_id, generation, settings.lease_seconds)
    if run is None:
        return
    if engine is None:
        from .runtime import run_graph
        engine = run_graph
    task = None
    try:
        actor = Identity(org, run["user_id"], "operator")
        ticket = await store.ticket(actor, str(run["ticket_id"]))
        task = asyncio.create_task(engine(store, settings, run, ticket))
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=max(1, settings.lease_seconds / 3))
            if not done and not await store.heartbeat(run, settings.lease_seconds):
                raise CancelledRun()
        status, projection = task.result()
    except CancelledRun:
        status, projection = "cancelled", {}
    except (TimeoutError, ConnectionError, OperationalError) as exc:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await store.retry(run, type(exc).__name__, settings.max_attempts)
        return
    except Exception as exc:
        # Provider exception bodies may contain prompts, credentials or PII.
        status, projection = "failed", {"error_code": type(exc).__name__}
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    await store.finish(run, status, projection)
