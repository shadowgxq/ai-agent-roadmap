"""Tenant-scoped repository; run, event and outbox writes share a transaction."""

from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import ConflictError, Identity, NotFoundError, TicketInput, ApprovalInput, TERMINAL, check_transition, request_hash, validate_key
from .security import public_projection, validate_crm_request


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

    async def cancel(self, identity: Identity, run_id: str):
        async with self.connection() as conn:
            run = await self.lock_run(conn, identity.organization_id, run_id)
            if run["status"] in TERMINAL:
                return run
            if run["status"] == "running":
                await conn.execute("UPDATE support_runs SET cancel_requested=true WHERE organization_id=%s AND run_id=%s", (identity.organization_id, run_id))
                if not run["cancel_requested"]:
                    await event(conn, identity.organization_id, run_id, "cancel_requested", {})
                return run | {"cancel_requested": True}
            return await self.change(conn, run, "cancelled", {})

    async def approve(self, identity: Identity, run_id: str, data: ApprovalInput):
        if data.decision in {"reject", "revise"} and not (data.feedback or "").strip():
            raise ValueError("Feedback is required for reject/revise")
        org = identity.organization_id
        async with self.connection() as conn:
            run = await self.lock_run(conn, org, run_id)
            cursor = await conn.execute("SELECT * FROM approvals WHERE organization_id=%s AND run_id=%s AND proposal_hash=%s", (org, run_id, data.proposal_hash))
            existing = await cursor.fetchone()
            if existing:
                if existing["decision"] != data.decision or existing["feedback"] != data.feedback or existing["actor_id"] != identity.user_id:
                    raise ConflictError("Proposal already has a different decision")
                return run
            if run["status"] != "waiting_approval" or run["projection"].get("proposal_hash") != data.proposal_hash:
                raise ConflictError("Proposal is no longer awaiting approval")
            payload = data.model_dump() | {"actor_id": identity.user_id}
            await conn.execute("""INSERT INTO approvals(id,organization_id,ticket_id,run_id,thread_id,actor_id,decision,feedback,proposal_hash)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                               (uuid4(), org, str(run["ticket_id"]), run_id, str(run["thread_id"]), identity.user_id,
                                data.decision, data.feedback, data.proposal_hash))
            await conn.execute("INSERT INTO support_audit(organization_id,run_id,audit_id,actor_id,action,payload) VALUES(%s,%s,%s,%s,'approval',%s)",
                               (org, run_id, uuid4(), identity.user_id, Jsonb({"decision": data.decision, "proposal_hash": data.proposal_hash})))
            await conn.execute("UPDATE support_runs SET generation=generation+1,resume_payload=%s WHERE organization_id=%s AND run_id=%s", (Jsonb(payload), org, run_id))
            updated = await self.change(conn, run, "queued", {"decision": data.decision})
            await conn.execute("INSERT INTO support_outbox(organization_id,run_id,generation) VALUES(%s,%s,%s)", (org, run_id, run["generation"] + 1))
            return updated | {"generation": run["generation"] + 1}

    async def lock_run(self, conn, org: str, run_id: str):
        cursor = await conn.execute("SELECT * FROM support_runs WHERE organization_id=%s AND run_id=%s FOR UPDATE", (org, run_id))
        run = await cursor.fetchone()
        if run is None:
            raise NotFoundError("Run not found")
        return run

    async def change(self, conn, run: dict, status: str, payload: dict):
        check_transition(run["status"], status)
        org, run_id = run["organization_id"], str(run["run_id"])
        await conn.execute("UPDATE support_runs SET status=%s,updated_at=now() WHERE organization_id=%s AND run_id=%s", (status, org, run_id))
        await event(conn, org, run_id, "done" if status in TERMINAL else "status", payload | {"status": status})
        return run | {"status": status}

    async def claim(self, org: str, run_id: str, generation: int, lease_seconds: int):
        async with self.connection() as conn:
            run = await self.lock_run(conn, org, run_id)
            if run["status"] != "queued" or run["generation"] != generation:
                return None
            if run["cancel_requested"]:
                await self.change(conn, run, "cancelled", {})
                return None
            token = uuid4()
            cursor = await conn.execute("""UPDATE support_runs SET lease_token=%s,lease_until=now()+(%s * interval '1 second'),attempt=attempt+1
                WHERE organization_id=%s AND run_id=%s RETURNING *""", (token, lease_seconds, org, run_id))
            claimed = await cursor.fetchone()
            await self.change(conn, run, "running", {})
            return claimed | {"status": "running"}

    async def finish(self, run: dict, status: str, projection: dict):
        projection = public_projection(projection)
        org, run_id = run["organization_id"], str(run["run_id"])
        async with self.connection() as conn:
            current = await self.lock_run(conn, org, run_id)
            if current["status"] != "running" or current["lease_token"] != run["lease_token"]:
                return False
            await conn.execute("UPDATE support_runs SET projection=%s,resume_payload=NULL,lease_token=NULL,lease_until=NULL WHERE organization_id=%s AND run_id=%s", (Jsonb(projection), org, run_id))
            await event(conn, org, run_id, "response", projection)
            await self.change(conn, current, "cancelled" if current["cancel_requested"] else status, {})
            return True

    async def progress(self, run: dict, values: dict):
        projection = public_projection(values)
        if not projection:
            return
        async with self.connection() as conn:
            current = await self.lock_run(conn, run["organization_id"], str(run["run_id"]))
            if current["status"] != "running" or current["lease_token"] != run["lease_token"]:
                raise ConflictError("Worker lease has been replaced")
            if current["cancel_requested"]:
                raise CancelledRun()
            await conn.execute("UPDATE support_runs SET projection=projection || %s WHERE organization_id=%s AND run_id=%s",
                               (Jsonb(projection), run["organization_id"], run["run_id"]))
            await event(conn, run["organization_id"], str(run["run_id"]), "response", projection)

    @asynccontextmanager
    async def tool_guard(self, run: dict, request: dict):
        validate_crm_request(run, request)
        async with self.connection() as conn:
            current = await self.lock_run(conn, run["organization_id"], str(run["run_id"]))
            if current["status"] != "running" or current["lease_token"] != run["lease_token"]:
                raise PermissionError("Worker does not own this run")
            cursor = await conn.execute("SELECT lease_until>now() AS valid FROM support_runs WHERE organization_id=%s AND run_id=%s", (run["organization_id"], run["run_id"]))
            if not (await cursor.fetchone())["valid"]:
                raise PermissionError("Worker lease expired")
            if current["cancel_requested"]:
                raise CancelledRun()
            proposal = current["projection"].get("proposal_hash")
            cursor = await conn.execute("SELECT decision FROM approvals WHERE organization_id=%s AND run_id=%s AND proposal_hash=%s",
                                       (run["organization_id"], str(run["run_id"]), proposal))
            approval = await cursor.fetchone()
            if not approval or approval["decision"] != "approve":
                raise PermissionError("Durable approval is required before CRM mutation")
            yield conn

    async def tool_audit(self, conn, run: dict, request: dict, result: dict):
        await conn.execute("""INSERT INTO support_audit(organization_id,run_id,audit_id,actor_id,action,payload,idempotency_key)
                             VALUES(%s,%s,%s,%s,'crm_update',%s,%s) ON CONFLICT(organization_id,idempotency_key) DO NOTHING""",
                           (run["organization_id"], run["run_id"], uuid4(), "worker", Jsonb(public_projection({"tool_result": result})), request["idempotency_key"]))


class CancelledRun(RuntimeError):
    pass
