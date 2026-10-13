import json
from types import SimpleNamespace
from uuid import uuid4

from support_agent.application.telemetry import Telemetry, create_telemetry, mask_trace


class SpanDouble:
    id = "1234567890abcdef"
    def __init__(self, captured):
        self.captured = captured
    def update(self, **kwargs):
        self.captured.append(kwargs)
    def end(self):
        pass


class ClientDouble:
    def __init__(self):
        self.captured = []
    def start_observation(self, **kwargs):
        self.captured.append(kwargs)
        return SpanDouble(self.captured)
    def create_score(self, **kwargs):
        self.captured.append(kwargs)
    def flush(self):
        pass


def test_trace_never_receives_raw_prompts_or_outputs_and_records_usage():
    client = ClientDouble()
    run = {"run_id": "run", "thread_id": "thread", "ticket_id": "ticket"}
    trace = Telemetry(run, "fixture", client=client, input_price=1.0, output_price=2.0)
    call_id = uuid4()
    with trace.observe("support-run"):
        trace.on_chat_model_start({"api_key": "sk-secret"}, ["customer@example.com password=private"], run_id=call_id)
        trace.on_llm_end(SimpleNamespace(llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 10}}, generations=[]), run_id=call_id)
        chain_id = uuid4()
        trace.on_chain_start(None, {"cookie": "secret"}, run_id=chain_id, name="classify_ticket")
        trace.on_chain_end({"answer": "private PII"}, run_id=chain_id)
        trace.score("succeeded")
    export = json.dumps(client.captured)
    assert "sk-secret" not in export and "customer@example.com" not in export and "private PII" not in export
    assert trace.metrics()["cost_usd"] == 0.00012
    assert trace.metrics()["input_tokens"] == 100
    assert "run_status" in export and "classify_ticket" in export


def test_tracing_is_disabled_by_default_and_unreported_usage_remains_unknown():
    trace = create_telemetry(SimpleNamespace(), {"run_id": "r", "thread_id": "t", "ticket_id": "ticket"}, "fixture")
    assert trace.client is None
    call_id = uuid4()
    trace.on_chat_model_start({}, [], run_id=call_id)
    trace.on_llm_end(SimpleNamespace(llm_output={}, generations=[]), run_id=call_id)
    assert trace.metrics()["cost_usd"] is None and trace.metrics()["input_tokens"] is None
    assert mask_trace(data={"cookie": "secret"}) == {"cookie": "[redacted]"}
