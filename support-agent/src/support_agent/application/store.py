"""Tenant-scoped repository; run, event and outbox writes share a transaction."""

from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import ConflictError, Identity, NotFoundError, TicketInput, request_hash, validate_key


async def event(conn, org: str, run_id: str, kind: str, payload: dict):
    cursor = await conn.execute(
        "UPDATE support_runs SET sequence=sequence+1,updated_at=now() WHERE organization_id=%s AND run_id=%s RETURNING sequence",
        (org, run_id))
    sequence = (await cursor.fetchone())["sequence"]
    await conn.execute("INSERT INTO support_run_events(organization_id,run_id,sequence,kind,payload) VALUES(%s,%s,%s,%s,%s)",
                       (org, run_id, sequence, kind, Jsonb(payload)))


class ApplicationStore:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @asynccontextmanager
    async def connection(self):
        async with await AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            yield conn

    async def create_ticket(self, identity: Identity, data: TicketInput):
        async with self.connection() as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM knowledge_bases WHERE organization_id=%s AND knowledge_base_id=%s",
                (identity.organization_id, data.knowledge_base_id))
            if not await cursor.fetchone():
                raise NotFoundError("Knowledge base not found")
            cursor = await conn.execute(
                """INSERT INTO support_tickets(organization_id,ticket_id,user_id,subject,description,knowledge_base_id)
                   VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
                (identity.organization_id, uuid4(), identity.user_id, data.subject, data.description, data.knowledge_base_id))
            return await cursor.fetchone()

    async def tickets(self, identity: Identity):
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM support_tickets WHERE organization_id=%s ORDER BY created_at DESC LIMIT 100", (identity.organization_id,))
            return await cursor.fetchall()

    async def ticket(self, identity: Identity, ticket_id: str):
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM support_tickets WHERE organization_id=%s AND ticket_id=%s", (identity.organization_id, ticket_id))
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError("Ticket not found")
            return row

    async def create_run(self, identity: Identity, ticket_id: str, key: str):
        validate_key(key)
        fingerprint = request_hash({"ticket_id": str(ticket_id)})
        org = identity.organization_id
        async with self.connection() as conn:
            # Serialize one tenant/key before checking both replay and active-run conflicts.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (org + ":" + key,))
            cursor = await conn.execute("SELECT * FROM support_runs WHERE organization_id=%s AND idempotency_key=%s", (org, key))
            existing = await cursor.fetchone()
            if existing:
                if existing["request_hash"] != fingerprint:
                    raise ConflictError("Idempotency key is bound to another request")
                return existing
            cursor = await conn.execute("SELECT * FROM support_tickets WHERE organization_id=%s AND ticket_id=%s FOR UPDATE", (org, ticket_id))
            if not await cursor.fetchone():
                raise NotFoundError("Ticket not found")
            cursor = await conn.execute("SELECT 1 FROM support_runs WHERE organization_id=%s AND ticket_id=%s AND status IN ('queued','running','waiting_approval')", (org, ticket_id))
            if await cursor.fetchone():
                raise ConflictError("Ticket already has an active run")
            run_id = uuid4()
            cursor = await conn.execute(
                """INSERT INTO support_runs(organization_id,run_id,ticket_id,thread_id,user_id,idempotency_key,request_hash)
                   VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (org, run_id, ticket_id, uuid4(), identity.user_id, key, fingerprint))
            run = await cursor.fetchone()
            await event(conn, org, str(run_id), "status", {"status": "queued"})
            await conn.execute("INSERT INTO support_outbox(organization_id,run_id,generation) VALUES(%s,%s,1)", (org, run_id))
            return run | {"sequence": 1}

    async def run(self, identity: Identity, run_id: str):
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM support_runs WHERE organization_id=%s AND run_id=%s", (identity.organization_id, run_id))
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError("Run not found")
            return row

    async def runs(self, identity: Identity, ticket_id: str):
        await self.ticket(identity, ticket_id)
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT * FROM support_runs WHERE organization_id=%s AND ticket_id=%s ORDER BY created_at DESC", (identity.organization_id, ticket_id))
            return await cursor.fetchall()

    async def events(self, identity: Identity, run_id: str, after: int):
        await self.run(identity, run_id)
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT sequence,kind,payload FROM support_run_events WHERE organization_id=%s AND run_id=%s AND sequence>%s ORDER BY sequence LIMIT 200", (identity.organization_id, run_id, after))
            return await cursor.fetchall()

    async def audit(self, identity: Identity, run_id: str):
        await self.run(identity, run_id)
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT actor_id,action,payload,created_at FROM support_audit WHERE organization_id=%s AND run_id=%s ORDER BY created_at,audit_id", (identity.organization_id, run_id))
            return await cursor.fetchall()
