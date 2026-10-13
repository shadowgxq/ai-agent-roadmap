"""Correlated Langfuse spans that never receive prompts, messages or raw tool output."""

from contextlib import contextmanager
from hashlib import sha256
from langchain_core.callbacks import BaseCallbackHandler

from .security import redact


NODES = frozenset({"normalize_ticket", "classify_ticket", "build_clarification", "response_subgraph",
                   "retrieve_policy", "draft_response", "assess_risk", "prepare_approval", "approval_gate", "execute_tool", "finalize"})


def mask_trace(*, data):
    return redact(data)


class Telemetry(BaseCallbackHandler):
    def __init__(self, run: dict, model: str, *, client=None, input_price=None, output_price=None):
        self.trace_id = sha256(str(run["run_id"]).encode()).hexdigest()[:32]
        self.metadata = {key: str(run[key]) for key in ("run_id", "thread_id", "ticket_id")}
        self.model, self.client = model, client
        self.input_price, self.output_price = input_price, output_price
        self.pending = {}
        self.root_id = None
        prior = run.get("projection", {}).get("metrics", {})
        self.calls = prior.get("model_calls", 0)
        self.input_tokens = prior.get("input_tokens") or 0
        self.output_tokens = prior.get("output_tokens") or 0
        self.complete = prior.get("usage_complete", True)

    def start(self, name, kind="span"):
        if self.client is None:
            return None
        try:
            context = {"trace_id": self.trace_id}
            if self.root_id:
                context["parent_span_id"] = self.root_id
            return self.client.start_observation(name=name, as_type=kind, trace_context=context,
                metadata=redact(self.metadata), **({"model": self.model} if kind == "generation" else {}))
        except Exception:
            return None

    @contextmanager
    def observe(self, name, kind="span"):
        span = self.start(name, kind)
        if name == "support-run" and span is not None:
            self.root_id = span.id
        try:
            yield span
        except Exception:
            if span is not None:
                span.update(level="ERROR", status_message="Operation failed")
            raise
        finally:
            if span is not None:
                span.end()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.calls += 1
        self.pending[run_id] = self.start("llm", "generation")

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = (response.llm_output or {}).get("token_usage", {})
        if not usage:
            for generations in response.generations:
                for generation in generations:
                    usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or usage
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (input_tokens, output_tokens))
        self.complete = self.complete and valid
        span = self.pending.pop(run_id, None)
        if valid:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            if span is not None:
                update = {"usage_details": {"input": input_tokens, "output": output_tokens}}
                if self.input_price is not None and self.output_price is not None:
                    update["cost_details"] = {"input": input_tokens * self.input_price / 1_000_000,
                                              "output": output_tokens * self.output_price / 1_000_000}
                span.update(**update)
        if span is not None:
            span.end()

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.complete = False
        span = self.pending.pop(run_id, None)
        if span is not None:
            span.update(level="ERROR", status_message="Model call failed")
            span.end()

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        name = kwargs.get("name")
        if name in NODES:
            self.pending[run_id] = self.start(name)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        span = self.pending.pop(run_id, None)
        if span is not None:
            span.end()

    def on_chain_error(self, error, *, run_id, **kwargs):
        span = self.pending.pop(run_id, None)
        if span is not None:
            span.update(level="ERROR", status_message="Graph node failed")
            span.end()

    def metrics(self):
        cost = None
        if self.complete and self.input_price is not None and self.output_price is not None:
            cost = (self.input_tokens * self.input_price + self.output_tokens * self.output_price) / 1_000_000
        return {"model_calls": self.calls, "input_tokens": self.input_tokens if self.complete else None,
                "output_tokens": self.output_tokens if self.complete else None, "usage_complete": self.complete,
                "cost_usd": cost, "cost_source": "configured-per-million-prices" if cost is not None else "unmeasured"}

    def score(self, status):
        if self.client is not None:
            try:
                self.client.create_score(name="run_status", value=status, data_type="CATEGORICAL",
                                         trace_id=self.trace_id, metadata=redact(self.metadata))
                self.client.flush()
            except Exception:
                pass


def create_telemetry(settings, run, model):
    client = None
    if getattr(settings, "tracing_enabled", False):
        from langfuse import Langfuse
        client = Langfuse(public_key=settings.langfuse_public_key,
                         secret_key=settings.langfuse_secret_key.get_secret_value(),
                         host=settings.langfuse_host, mask=mask_trace, environment="support-demo")
    return Telemetry(run, model, client=client,
                     input_price=getattr(settings, "input_price_per_million", None),
                     output_price=getattr(settings, "output_price_per_million", None))
