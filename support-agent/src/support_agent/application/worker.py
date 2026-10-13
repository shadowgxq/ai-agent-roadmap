"""One leased task attempt; injected engines keep local checks provider-free."""

from .contracts import Identity


async def execute_run(store, settings, org: str, run_id: str, generation: int, engine=None):
    run = await store.claim(org, run_id, generation, settings.lease_seconds)
    if run is None:
        return
    if engine is None:
        from .runtime import run_graph
        engine = run_graph
    actor = Identity(org, run["user_id"], "operator")
    ticket = await store.ticket(actor, str(run["ticket_id"]))
    try:
        status, projection = await engine(store, settings, run, ticket)
    except Exception as exc:
        # Provider exception bodies may contain prompts, credentials or PII.
        status, projection = "failed", {"error_code": type(exc).__name__}
    await store.finish(run, status, projection)
