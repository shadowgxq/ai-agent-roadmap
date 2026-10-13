"""Celery import registers tasks; database/broker/model I/O happens only in tasks."""

import asyncio
import os
from celery import Celery
from dotenv import load_dotenv
from support_agent.config.settings import PROJECT_ROOT

from .settings import ApplicationSettings
from .store import ApplicationStore


load_dotenv(PROJECT_ROOT / ".env", override=False)
celery_app = Celery("support", broker=os.getenv("SUPPORT_APP_REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True,
                       worker_prefetch_multiplier=1, task_ignore_result=True,
                       beat_schedule={"support-outbox": {"task": "support.dispatch", "schedule": 5.0},
                                      "support-recover": {"task": "support.recover", "schedule": 30.0}})


async def dispatch_pending(store, publish):
    async with store.connection() as conn:
        cursor = await conn.execute("SELECT * FROM support_outbox WHERE NOT dispatched ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 100")
        for message in await cursor.fetchall():
            publish(message["organization_id"], str(message["run_id"]), message["generation"])
            await conn.execute("UPDATE support_outbox SET dispatched=true WHERE organization_id=%s AND run_id=%s AND generation=%s",
                               (message["organization_id"], message["run_id"], message["generation"]))


@celery_app.task(name="support.dispatch")
def dispatch():
    settings = ApplicationSettings()
    asyncio.run(dispatch_pending(ApplicationStore(settings.database_url),
                                 lambda org, run_id, generation: execute.delay(org, run_id, generation)))


@celery_app.task(name="support.execute")
def execute(org: str, run_id: str, generation: int):
    from .worker import execute_run
    settings = ApplicationSettings()
    try:
        asyncio.run(execute_run(ApplicationStore(settings.database_url), settings, org, run_id, generation))
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


@celery_app.task(name="support.recover")
def recover():
    settings = ApplicationSettings()
    asyncio.run(ApplicationStore(settings.database_url).recover(settings.max_attempts, settings.lease_seconds))
