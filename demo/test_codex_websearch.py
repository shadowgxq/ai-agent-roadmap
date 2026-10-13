"""Offline probe tests: fake credentials, fake response, and blocked network."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import codex_websearch as probe
import deepseek_websearch as original

CONFIG = {
    "CODEX_API_KEY": "fake-offline-key",
    "CODEX_BASE_URL": "https://example.org/v1",
    "CODEX_MODEL": "mock-search-model",
}

FIXTURE = {
    "id": "resp_mock",
    "model": CONFIG["CODEX_MODEL"],
    "status": "completed",
    "output": [
        {"type": "reasoning", "encrypted_content": "do-not-print-this"},
        {
            "type": "web_search_call",
            "id": "ws_mock",
            "status": "completed",
            "action": {
                "type": "search",
                "queries": ["mock query"],
                "sources": [
                    {
                        "type": "url",
                        "url": "https://example.org/news",
                        "title": "Mock source",
                        "encrypted_content": "hidden",
                    }
                ],
            },
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Mock answer.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://example.org/news",
                            "title": "Mock source",
                            "start_index": 0,
                            "end_index": 12,
                        }
                    ],
                },
                {"type": "output_text", "text": "Second paragraph.", "annotations": []},
            ],
        },
    ],
}


class ProbeTests(unittest.TestCase):
    def setUp(self):
        # Any unmocked network request or real .env read must fail the test.
        self.network = patch.object(
            probe, "urlopen", side_effect=AssertionError("Network forbidden")
        )
        self.env = patch.object(
            probe,
            "load_project_env_value",
            side_effect=AssertionError(".env forbidden"),
        )
        self.process_env = patch.dict(probe.os.environ, {}, clear=True)
        self.network.start()
        self.env.start()
        self.process_env.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.env.stop)
        self.addCleanup(self.process_env.stop)

    def test_request_uses_responses_auth_and_required_search(self):
        request = probe.build_request(
            "mock query",
            "fake-offline-key",
            base_url=CONFIG["CODEX_BASE_URL"],
            model=CONFIG["CODEX_MODEL"],
        )
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://example.org/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-offline-key")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(payload["model"], "mock-search-model")
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertEqual(payload["tools"], [{"type": "web_search"}])
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(payload["include"], ["web_search_call.action.sources"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_output_tokens"], 1500)
        self.assertNotIn("max_tool_calls", payload)
        self.assertNotIn("text", payload)
        self.assertNotIn("messages", payload)

    def test_search_sources_citations_and_all_text_blocks(self):
        report = probe.inspect_response(FIXTURE)
        self.assertTrue(report["search_evidence_present"])
        self.assertEqual(report["completed_search_calls"], 1)
        self.assertEqual(report["answer"], "Mock answer.\nSecond paragraph.")
        self.assertEqual(report["sources"][0]["url"], "https://example.org/news")
        self.assertEqual(report["citations"][0]["start_index"], 0)
        self.assertNotIn("encrypted_content", json.dumps(report))

    def test_text_even_with_citation_does_not_prove_search(self):
        response = copy.deepcopy(FIXTURE)
        response["output"] = response["output"][2:]
        self.assertFalse(probe.inspect_response(response)["search_evidence_present"])

    def test_incomplete_failed_and_missing_provenance_are_unconfirmed(self):
        for mode in (
            "incomplete",
            "failed_tool",
            "no_sources",
            "no_answer",
            "open_only",
        ):
            with self.subTest(mode=mode):
                response = copy.deepcopy(FIXTURE)
                if mode == "incomplete":
                    response["status"] = "incomplete"
                    response["incomplete_details"] = {"reason": "max_output_tokens"}
                elif mode == "failed_tool":
                    response["output"][1]["status"] = "failed"
                elif mode == "no_sources":
                    response["output"][1]["action"]["sources"] = []
                    response["output"][2]["content"][0]["annotations"] = []
                elif mode == "no_answer":
                    response["output"][2]["content"] = []
                else:
                    response["output"][1]["action"]["type"] = "open_page"
                self.assertFalse(
                    probe.inspect_response(response)["search_evidence_present"]
                )

    def test_env_loader_order_uses_only_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agent-mini").mkdir()
            (root / ".env").write_text('export CODEX_API_KEY="fake-root"\n')
            (root / "agent-mini" / ".env").write_text("CODEX_API_KEY='fake-agent'\n")
            with patch.object(original, "PROJECT_ROOT", root):
                self.assertEqual(
                    original.load_project_env_value("CODEX_API_KEY"), "fake-root"
                )
                (root / ".env").unlink()
                self.assertEqual(
                    original.load_project_env_value("CODEX_API_KEY"), "fake-agent"
                )

    def test_single_request_prints_evidence_and_no_key(self):
        output = io.StringIO()
        with (
            patch.object(probe, "load_project_env_value", side_effect=CONFIG.get),
            patch.object(
                probe, "urlopen", return_value=io.StringIO(json.dumps(FIXTURE))
            ) as send,
            patch("sys.argv", ["codex_websearch.py", "mock query"]),
            redirect_stdout(output),
            self.assertLogs(probe.LOGGER, level="INFO") as logs,
        ):
            self.assertEqual(probe.main(), 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs, {"timeout": 120})
        transcript = output.getvalue() + "\n".join(logs.output)
        self.assertIn("ws_mock", transcript)
        self.assertIn("Mock answer.", transcript)
        self.assertIn("https://example.org/news", transcript)
        self.assertNotIn("fake-offline-key", transcript)
        self.assertNotIn("do-not-print-this", transcript)

    def test_http_error_and_timeout_do_not_retry_or_leak_key(self):
        errors = [
            HTTPError(
                "https://example.org",
                400,
                "bad request",
                {},
                io.BytesIO(
                    b'{"error":"Unsupported parameter: max_tool_calls; fake-offline-key"}'
                ),
            ),
            URLError(TimeoutError("timed out")),
        ]
        for error in errors:
            with (
                self.subTest(error=type(error).__name__),
                patch.object(probe, "load_project_env_value", side_effect=CONFIG.get),
                patch.object(probe, "urlopen", side_effect=error) as send,
                patch("sys.argv", ["codex_websearch.py", "mock query"]),
                self.assertLogs(probe.LOGGER, level="INFO") as logs,
            ):
                self.assertEqual(probe.main(), 1)
                self.assertEqual(send.call_count, 1)
                self.assertNotIn("fake-offline-key", "\n".join(logs.output))

    def test_main_returns_nonzero_for_plain_text_response(self):
        response = {"status": "completed", "output": FIXTURE["output"][2:]}
        with (
            patch.object(probe, "load_project_env_value", side_effect=CONFIG.get),
            patch.object(
                probe, "urlopen", return_value=io.StringIO(json.dumps(response))
            ),
            patch("sys.argv", ["codex_websearch.py", "mock query"]),
            redirect_stdout(io.StringIO()),
            self.assertLogs(probe.LOGGER, level="INFO"),
        ):
            self.assertEqual(probe.main(), 2)

    def test_process_config_takes_precedence_and_normalizes_base_url(self):
        with patch.dict(
            probe.os.environ, CONFIG | {"CODEX_BASE_URL": "https://example.org/v1/"}
        ):
            self.assertEqual(
                probe.load_config(),
                ("fake-offline-key", "https://example.org/v1", "mock-search-model"),
            )

    def test_missing_config_stops_before_network_request(self):
        for name in CONFIG:
            values = CONFIG | {name: ""}
            with (
                self.subTest(name=name),
                patch.dict(probe.os.environ, values),
                self.assertLogs(probe.LOGGER, level="ERROR"),
            ):
                self.assertEqual(probe.main(), 1)

    def test_base_url_rejects_credentials_query_and_unsupported_scheme(self):
        for url in (
            "ftp://example.org",
            "https://user:secret@example.org/v1",
            "https://example.org/v1?token=secret",
            "https://example.org/v1#fragment",
            "https://",
        ):
            with (
                self.subTest(url=url),
                patch.dict(probe.os.environ, CONFIG | {"CODEX_BASE_URL": url}),
                self.assertRaises(ValueError),
            ):
                probe.load_config()

    def test_nonobject_response_fails_without_an_uncaught_exception(self):
        with (
            patch.dict(probe.os.environ, CONFIG),
            patch.object(probe, "urlopen", return_value=io.StringIO("[]")),
            self.assertLogs(probe.LOGGER, level="ERROR"),
        ):
            self.assertEqual(probe.main(), 1)


if __name__ == "__main__":
    unittest.main()
