"""W19 local checks: no database service and no provider calls."""

import asyncio
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import pytest
import tiktoken

from support_agent.graphs.ticket import create_response_subgraph, draft_response
from support_agent.knowledge.audit import citation_audit_report
from support_agent.knowledge.citations import ABSTENTION, validate_citations
from support_agent.knowledge.evaluation import RetrievalCase, evaluate_retrieval, ranking_metrics
from support_agent.knowledge.models import Document, EvidenceRef
from support_agent.knowledge.parsing import chunk_sections, parse_source
from support_agent.knowledge.repository import KnowledgeRepository, vector_literal
from support_agent.knowledge.reranking import compare_reranking, diagnose_ranking
from support_agent.knowledge.retrieval import RetrievalResult, reciprocal_rank_fusion
from support_agent.models import EvidenceRef as TicketEvidence


EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals"


@pytest.fixture(autouse=True)
def forbid_provider_and_database_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("W19 offline checks cannot connect to databases or call model providers")

    monkeypatch.setattr("psycopg.AsyncConnection.connect", forbidden)
    monkeypatch.setattr("langchain_openai.ChatOpenAI.invoke", forbidden)
    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings.aembed_query", forbidden)
    monkeypatch.setattr("langchain_openai.OpenAIEmbeddings.aembed_documents", forbidden)


def pdf_bytes(pages: list[str]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        commands = ["BT /F1 12 Tf 14 TL 72 720 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj T*")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode())
        page[NameObject("/Contents")] = stream
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


CHUNK_CASES = json.loads((EVAL_ROOT / "chunk_cases.json").read_text())


@pytest.mark.parametrize("case", CHUNK_CASES, ids=lambda case: case["id"])
def test_chunk_boundary_fixtures(case):
    if case["format"] == "pdf":
        content = pdf_bytes(case["pages"])
    else:
        text = case["text"]
        if "repeat_body" in case:
            text += case["repeat_body"] * case["repeat"] + case["end"]
        elif "repeat" in case:
            text *= case["repeat"]
        content = text.encode()
    sections = parse_source(content, "." + case["format"])
    chunks = chunk_sections(sections, max_tokens=128, overlap_tokens=12)
    encoding = tiktoken.get_encoding("cl100k_base")
    assert chunks
    assert all(len(encoding.encode(chunk.text, disallowed_special=())) <= 128 for chunk in chunks)
    assert all("\ufffd" not in chunk.text for chunk in chunks)
    if case["format"] == "pdf":
        assert {chunk.page for chunk in chunks} == {1, 2, 3}
        assert all("Internal knowledge" not in chunk.text for chunk in chunks)
        assert all("Refund policy" not in chunk.text for chunk in chunks)
    elif case["id"] == "nested_headings":
        assert [chunk.heading_path for chunk in chunks] == [["Accounts", "Email"], ["Accounts", "Recovery"]]
    elif case["id"] == "code_fence":
        assert len(chunks) == 1 and chunks[0].heading_path == ["API"]
        assert "# this is not a heading" in chunks[0].text
    elif case["id"] == "list_conditions":
        assert "- Purchase within 30 days.\n  Receipt must match the customer." in chunks[0].text
    elif case["id"] == "unicode_long_paragraph":
        assert chunks[0].text.startswith("账户变更")
        assert chunks[-1].text.endswith("验证身份。")


def ref(cid: str, document: str = "refund", score: float = 1.0) -> EvidenceRef:
    return EvidenceRef(chunk_id=cid, document_id=document, document_title=document,
                       document_version=1, heading_path=["Policy"], snippet="Refund within 30 days", score=score)


def test_rrf_uses_ranks_and_deduplicates():
    result = reciprocal_rank_fusion([ref("a", score=0.01), ref("b", score=100)],
                                    [ref("b"), ref("b"), ref("c")])
    assert result[0].chunk_id == "b"
    assert len({item.chunk_id for item in result}) == len(result)
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)


@pytest.mark.parametrize("vector", [[0, 0], [1], [float("nan"), 1], [float("inf"), 1]])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        vector_literal(vector, 2)


def test_recall_counts_unique_relevant_documents():
    case = RetrievalCase(id="multi", query="refund and charges", relevant_documents=["refund", "charge"])
    metrics = ranking_metrics([ref("r1"), ref("r2"), ref("c1", "charge")], case)
    assert metrics["recall@1"] == 0.5
    assert metrics["recall@3"] == metrics["recall@5"] == 1


@pytest.mark.parametrize("answer", ["policy-id outside brackets", "[made-up]", "[policy-id] [made-up]"])
def test_citation_membership_cannot_be_satisfied_by_substring(answer):
    assert not validate_citations(answer, {"policy-id"}).valid


def test_empty_evidence_abstains_without_a_model():
    result = draft_response({"normalized_text": "unanswerable", "evidence_refs": []}, model=None)
    assert result["status"] == "abstained"
    assert result["draft_response"] == ABSTENTION
    assert result["requires_approval"] is False


def test_illegal_citation_blocks_publishing_the_draft():
    model = SimpleNamespace(invoke=lambda _: AIMessage(content="Refund approved [valid] [forged]"))
    result = draft_response({"normalized_text": "refund", "evidence_refs": [
        TicketEvidence(source_id="valid", title="policy", snippet="Request approval")
    ]}, model=model)
    assert result["status"] == "failed"
    assert result["draft_response"] == ABSTENTION
    assert result["citation_invalid_ids"] == ["forged"]


def test_hybrid_response_rejects_state_tenant_spoofing():
    class NeverRetrieve:
        async def retrieve(self, *args, **kwargs):
            pytest.fail("Mismatching tenant must be rejected before retrieval")
    graph = create_response_subgraph(retriever=NeverRetrieve(), organization_id="org-a", knowledge_base_id="kb")
    result = asyncio.run(graph.ainvoke({"organization_id": "org-b", "normalized_text": "secret", "status": "pending"}))
    assert result["status"] == "failed" and result["evidence_refs"] == []


def test_hybrid_no_answer_does_not_enter_risk_or_approval():
    class EmptyRetriever:
        async def retrieve(self, org, kb, query):
            return RetrievalResult(query, org, kb)
    graph = create_response_subgraph(retriever=EmptyRetriever(), organization_id="org-a", knowledge_base_id="kb")
    result = asyncio.run(graph.ainvoke({"organization_id": "org-a", "normalized_text": "unknown", "status": "pending"}))
    assert result["status"] == "abstained" and result["draft_response"] == ABSTENTION


def test_missing_human_annotations_cannot_pass_citation_audit():
    rows = [{"id": str(index), "evidence": [ref("valid").model_dump()],
             "answer": "Refund within 30 days [valid]", "status": "drafted"} for index in range(20)]
    report = citation_audit_report(rows)
    assert report["reviewed_count"] == 0 and not report["audit_gate_passed"]


def test_failed_eval_cases_cannot_inflate_retrieval_gate():
    cases = [RetrievalCase.model_validate(row) for row in json.loads((EVAL_ROOT / "retrieval_cases.json").read_text())]
    assert len(cases) == 50
    class FailedRetriever:
        embedding_model = "offline-double"
        min_similarity = 0.35
        async def retrieve(self, *args, **kwargs):
            raise RuntimeError("simulated provider failure")
    report = asyncio.run(evaluate_retrieval(FailedRetriever(), cases))
    assert report["error_count"] == 50 and not report["retrieval_gate_passed"]
    assert report["summary"]["hybrid"]["no_answer_false_positive_rate"] is None


def test_optional_reranker_requires_observed_baseline():
    assert diagnose_ranking({})["decision"] == "needs_data"
    assert compare_reranking({}, {})["decision"] == "needs_data"


class IngestionConnection:
    """Record publication boundaries without pretending to be a PostgreSQL engine."""

    def __init__(self, existing=None):
        self.existing = existing
        self.statements = []
        self.exit_error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception, traceback):
        self.exit_error = exception_type

    async def execute(self, query, params=None):
        self.statements.append((query, params))
        if "SELECT * FROM knowledge_bases" in query:
            value = {"embedding_model": "offline", "embedding_dimensions": 2, "pipeline_version": "v1"}
        elif "GROUP BY v.version" in query:
            value = self.existing
        elif "COALESCE(max(version)" in query:
            value = {"version": 2}
        else:
            value = None
        async def fetchone():
            return value
        return SimpleNamespace(fetchone=fetchone)


def ingest_with(connection, embed, monkeypatch):
    async def connect(*args, **kwargs):
        return connection
    monkeypatch.setattr("psycopg.AsyncConnection.connect", connect)
    from support_agent.knowledge.models import ChunkDraft
    return asyncio.run(KnowledgeRepository("unused").ingest(
        Document(organization_id="org-a", knowledge_base_id="kb", document_id="policy",
                 title="Refunds", source="fixture"), b"content",
        lambda: [ChunkDraft(text="Refund within 30 days")], embed))


def test_repeated_content_skips_embedding(monkeypatch):
    connection = IngestionConnection(existing={"version": 1, "chunk_count": 2})
    async def forbidden_embed(texts):
        pytest.fail("Unchanged content must not call embedding provider")
    result = ingest_with(connection, forbidden_embed, monkeypatch)
    assert result.reused and result.version == 1 and result.chunk_count == 2
    assert not any("INSERT INTO knowledge_chunks" in query for query, _ in connection.statements)


@pytest.mark.parametrize("failure", ["provider", "wrong_batch", "zero_vector"])
def test_failed_build_never_publishes_active_version(monkeypatch, failure):
    connection = IngestionConnection()
    async def failing_embed(texts):
        if failure == "provider":
            raise RuntimeError("simulated timeout")
        return [] if failure == "wrong_batch" else [[0, 0]]
    with pytest.raises((RuntimeError, ValueError)):
        ingest_with(connection, failing_embed, monkeypatch)
    assert connection.exit_error in {RuntimeError, ValueError}
    assert not any("UPDATE knowledge_documents" in query for query, _ in connection.statements)
    assert not any("INSERT INTO knowledge_versions" in query for query, _ in connection.statements)


def test_publish_occurs_only_after_all_chunks_are_written(monkeypatch):
    connection = IngestionConnection()
    async def embed(texts):
        return [[1, 0]]
    result = ingest_with(connection, embed, monkeypatch)
    assert result.version == 2 and not result.reused
    statements = [query for query, _ in connection.statements]
    write_index = next(index for index, query in enumerate(statements) if "INSERT INTO knowledge_chunks" in query)
    publish_index = next(index for index, query in enumerate(statements) if "UPDATE knowledge_documents" in query)
    assert write_index < publish_index
    assert connection.exit_error is None
