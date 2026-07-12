from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication
from hermes_service.cli import (
    INTERNAL_EVALUATION_PROJECTION_ENV,
    INTERNAL_ATTEMPT_ORIGIN_ENV,
    INTERNAL_LEARNING_ATTEMPT_ORIGIN_ENV,
    configured_evaluation_projection,
    configured_learning_attempt_origin,
    configured_study_pack_attempt_origin,
    main as cli_main,
)
from lumi_study_pack.parsing import ExtractedPdf


ENTITY_ID = re.compile(r"^(?:p_|d_|s_|a_|v_|t_)[A-P]{40}$")
PACK_ID = re.compile(r"^p_[A-P]{40}$")
DOCUMENT_ID = re.compile(r"^d_[A-P]{40}$")
SPAN_ID = re.compile(r"^s_[A-P]{40}$")
ARTIFACT_ID = re.compile(r"^a_[A-P]{40}$")
ATTEMPT_ID = re.compile(r"^t_[A-P]{40}$")
SECRET_LIKE_OPENAI = "".join(("sk-", "proj-", "abcdefghijklmnopqrstuvwxyz0123456789"))
SECRET_LIKE_GITHUB = "".join(
    ("github_", "pat_", "abcdefghijklmnopqrstuvwxyz0123456789")
)


def opaque_command(label: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    raw = hashlib.sha256(label.encode("utf-8")).digest()[:20]
    return "c_" + "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in raw
    )


class EmptyTextPdfBackend:
    def extract(self, _pdf_bytes: bytes, _deadline_seconds: float) -> ExtractedPdf:
        return ExtractedPdf(
            page_count=1,
            encrypted=False,
            page_texts=("",),
            parser_name="qa-empty-text-layer",
            parser_version="1.0.0",
        )


class TextLayerPdfBackend:
    def __init__(self, pages: tuple[str, ...]) -> None:
        self.pages = pages

    def extract(self, _pdf_bytes: bytes, _deadline_seconds: float) -> ExtractedPdf:
        return ExtractedPdf(
            page_count=len(self.pages),
            encrypted=False,
            page_texts=self.pages,
            parser_name="qa-text-layer-parser",
            parser_version="1.0.0",
        )


class EncryptedPdfBackend:
    def extract(self, _pdf_bytes: bytes, _deadline_seconds: float) -> ExtractedPdf:
        return ExtractedPdf(
            page_count=1,
            encrypted=True,
            page_texts=("",),
            parser_name="qa-encrypted-pdf",
            parser_version="1.0.0",
        )


class StudyPackApiTests(unittest.TestCase):
    maxDiff = None

    def test_documented_source_checkout_cli_resolves_study_pack_package(self) -> None:
        service_root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_service",
                    "--db",
                    str(Path(directory) / "sidecar.sqlite3"),
                    "capabilities",
                ],
                cwd=service_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["service_version"], "0.3.0")
        self.assertIn("local-cited-study-pack-v1", payload["features"])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sidecar.sqlite3"
        self.sentences = (
            "资料分析先确认统计口径，再定位基期量与现期量。",
            "增长量等于现期量减去基期量，不能与增长率混用。",
            "增长率计算必须以基期量为分母，并检查百分号单位。",
            "比较两个增速时，应先统一时间范围和指标定义。",
            "完成计算后要回到题干核对问题所求和数据单位。",
        )
        self.source_text = "\n\n".join(self.sentences)
        self._start_server()

    def tearDown(self) -> None:
        self._stop_server()
        self.temporary.cleanup()

    def _start_server(
        self,
        *,
        pdf_backend: Any | None = None,
        attempt_evidence_origin: str = "human_local_interactive",
    ) -> None:
        self.application = SidecarApplication(
            self.database,
            study_pack_pdf_backend=pdf_backend,
            study_pack_attempt_evidence_origin=attempt_evidence_origin,
        )
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def _stop_server(self) -> None:
        if getattr(self, "server", None) is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = None

    def restart(
        self,
        *,
        pdf_backend: Any | None = None,
        attempt_evidence_origin: str = "human_local_interactive",
    ) -> None:
        self._stop_server()
        self._start_server(
            pdf_backend=pdf_backend,
            attempt_evidence_origin=attempt_evidence_origin,
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | list[Any] | None = None,
        *,
        raw: bytes | None = None,
        content_type: str = "application/json",
        timeout: float = 10,
    ) -> tuple[int, dict[str, Any]]:
        data = raw
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": content_type} if data is not None else {}
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        try:
            encoded = response.read()
            return response.status, json.loads(encoded) if encoded else {}
        finally:
            response.close()

    def request_with_declared_length(
        self,
        path: str,
        declared_length: int,
    ) -> tuple[int, dict[str, Any]]:
        host, raw_port = self.base.removeprefix("http://").split(":", 1)
        connection = http.client.HTTPConnection(host, int(raw_port), timeout=5)
        try:
            connection.putrequest("POST", path)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(declared_length))
            connection.endheaders()
            response = connection.getresponse()
            encoded = response.read()
            return response.status, json.loads(encoded) if encoded else {}
        finally:
            connection.close()

    def create_pack(
        self,
        label: str = "create-pack",
        *,
        title: str = "资料分析基础",
        source: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self.request(
            "POST",
            "/v1/study-packs",
            {
                "title": title,
                "command_id": command_id or opaque_command(label),
                "source": source or {"kind": "pasted_text", "text": self.source_text},
            },
        )

    def command(
        self,
        pack: dict[str, Any],
        action: str,
        label: str,
        *,
        expected_version: int | None = None,
        command_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self.request(
            "POST",
            f"/v1/study-packs/{pack['pack_id']}/commands",
            {
                "action": action,
                "expected_version": (
                    pack["version"] if expected_version is None else expected_version
                ),
                "command_id": command_id or opaque_command(label),
            },
        )

    def publish_pack(self) -> dict[str, Any]:
        status, created = self.create_pack()
        self.assertEqual(status, 201)
        status, reviewed = self.command(created, "request_review", "review-pack")
        self.assertEqual(status, 200)
        self.assertEqual(reviewed["lifecycle"], "review")
        status, published = self.command(reviewed, "publish", "publish-pack")
        self.assertEqual(status, 200)
        self.assertEqual(published["lifecycle"], "published")
        return published

    def answer_for_launch(self, prompt: str) -> str:
        if "____" in prompt:
            prompt_body = prompt.split("：", 1)[-1]
            before, after = prompt_body.split("____", 1)
            matches = [
                sentence
                for sentence in self.sentences
                if sentence.startswith(before) and sentence.endswith(after)
            ]
            self.assertEqual(len(matches), 1)
            sentence = matches[0]
            end = len(sentence) - len(after) if after else len(sentence)
            return sentence[len(before) : end]
        prompt_match = re.search(r"第\s*(\d+)\s*条", prompt)
        self.assertIsNotNone(prompt_match)
        return self.sentences[int(prompt_match.group(1)) - 1]

    def assert_error(
        self,
        response: tuple[int, dict[str, Any]],
        status: int,
        code: str,
        *,
        forbidden: tuple[str, ...] = (),
    ) -> None:
        actual_status, payload = response
        self.assertEqual(actual_status, status)
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(set(payload["error"]), {"code", "message", "request_id"})
        self.assertEqual(payload["error"]["code"], code)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for value in forbidden:
            self.assertNotIn(value.lower(), serialized)

    def assert_practice_artifacts_redacted(self, pack: dict[str, Any]) -> None:
        self.assertEqual(pack["schema_version"], "lumi.study-pack-detail.v1")
        required = {
            "schema_version",
            "pack_id",
            "title",
            "lifecycle",
            "version",
            "source",
            "artifact_set_digest",
            "artifact_counts",
            "artifacts",
            "candidate_skill_links",
            "attempt_history",
            "review",
            "quarantine_reason",
            "generator",
            "learning_projection_writes",
            "created_at",
            "updated_at",
            "links",
        }
        self.assertTrue(required.issubset(pack))
        self.assertTrue(set(pack).issubset(required | {"idempotent_replay"}))
        for entry in pack["attempt_history"]:
            self.assertEqual(
                set(entry),
                {
                    "schema_version",
                    "attempt",
                    "prompt",
                    "learner_answer",
                    "result",
                    "answer",
                    "explanation",
                    "cited_source_context",
                    "created_at",
                },
            )
            self.assertEqual(
                entry["attempt"]["evidence_origin"], "human_local_interactive"
            )
            self.assertEqual(set(entry["result"]), {"correct", "score", "max_score"})
            for context in entry["cited_source_context"]:
                self.assertIn("slice_sha256", context)
        self.assertEqual(
            set(pack["source"]),
            {
                "document_id",
                "source_version",
                "input_kind",
                "media_type",
                "original_sha256",
                "normalized_sha256",
                "byte_count",
                "locator_count",
                "codepoint_count",
                "parser_name",
                "parser_version",
                "normalization_name",
                "normalization_version",
                "extraction_state",
                "warning_codes",
            },
        )
        self.assertIn(
            pack["source"]["extraction_state"],
            {"accepted", "accepted_with_warnings"},
        )
        self.assertEqual(
            set(pack["review"]),
            {
                "accepted",
                "decision_count",
                "accepted_count",
                "decision_refs",
                "reason_codes",
            },
        )
        for decision in pack["review"]["decision_refs"]:
            self.assertEqual(
                set(decision),
                {
                    "decision_id",
                    "artifact_id",
                    "artifact_version",
                    "artifact_digest",
                    "verifier_id",
                    "accepted",
                    "reason_codes",
                },
            )
        self.assertEqual(
            set(pack["generator"]),
            {"id", "model_calls", "network_calls", "ocr_calls"},
        )
        self.assertEqual(
            set(pack["learning_projection_writes"]),
            {"kt", "misconception", "today_plan", "review_schedule"},
        )
        self.assertFalse(any(pack["learning_projection_writes"].values()))
        self.assertEqual(set(pack["links"]), {"self", "commands", "replay"})
        artifact_base = {
            "artifact_id",
            "pack_id",
            "artifact_version",
            "artifact_type",
            "lifecycle",
            "content_digest",
            "generator_id",
            "generator_metadata",
            "content",
        }
        for artifact in pack.get("artifacts", []):
            expected_artifact_keys = artifact_base | (
                {"links"}
                if artifact.get("artifact_type") == "study_pack.practice_item"
                else set()
            )
            self.assertEqual(set(artifact), expected_artifact_keys)
            self.assertEqual(
                set(artifact["generator_metadata"]),
                {
                    "generator_id",
                    "mode",
                    "model_calls",
                    "network_calls",
                    "ocr_calls",
                    "source_normalized_sha256",
                },
            )
            self.assertEqual(artifact["generator_metadata"]["model_calls"], 0)
            self.assertEqual(artifact["generator_metadata"]["network_calls"], 0)
            self.assertEqual(artifact["generator_metadata"]["ocr_calls"], 0)
            content = artifact["content"]
            if artifact["artifact_type"] == "study_pack.one_page_notes":
                self.assertEqual(
                    set(content), {"schema_version", "title", "claims", "citations"}
                )
                self.assertTrue(all(8 <= len(claim) <= 2_000 for claim in content["claims"]))
            elif artifact["artifact_type"] == "study_pack.knowledge_card":
                self.assertEqual(
                    set(content), {"schema_version", "question", "answer", "citations"}
                )
                self.assertLessEqual(len(content["answer"]), 2_000)
            elif artifact["artifact_type"] == "study_pack.review_task":
                self.assertEqual(
                    set(content),
                    {
                        "schema_version",
                        "instruction",
                        "citations",
                        "scope",
                        "schedule_write_capability",
                    },
                )
                self.assertLessEqual(len(content["instruction"]), 2_500)
                self.assertFalse(content["schedule_write_capability"])
        for link in pack["candidate_skill_links"]:
            self.assertEqual(
                set(link),
                {
                    "artifact_id",
                    "label",
                    "skill_id",
                    "status",
                    "taxonomy_version",
                    "taxonomy_digest",
                },
            )
            self.assertEqual(link["status"], "unconfirmed_candidate")
        practice = [
            artifact
            for artifact in pack.get("artifacts", [])
            if artifact.get("artifact_type") == "study_pack.practice_item"
        ]
        self.assertEqual(len(practice), 3)
        for artifact in practice:
            self.assertRegex(artifact["artifact_id"], ARTIFACT_ID)
            self.assertEqual(
                set(artifact["content"]),
                {"schema_version", "item_kind", "prompt", "scorer"},
            )
            self.assertNotIn("answer", artifact)
            self.assertNotIn("explanation", artifact)
            self.assertNotIn("citations", artifact)
            self.assertNotIn("answer", artifact["content"])
            self.assertNotIn("explanation", artifact["content"])
            self.assertNotIn("citations", artifact["content"])
            self.assertEqual(set(artifact["links"]), {"launch"})

    def assert_attempt_result_closed(self, result: dict[str, Any]) -> None:
        self.assertEqual(
            set(result),
            {
                "schema_version",
                "pack_id",
                "pack_version",
                "attempt",
                "result",
                "answer",
                "explanation",
                "cited_source_context",
                "learning_projection_writes",
                "idempotent_replay",
                "links",
            },
        )
        self.assertEqual(
            result["schema_version"], "lumi.study-pack-attempt-result.v1"
        )
        self.assertEqual(
            set(result["attempt"]),
            {
                "schema_version",
                "attempt_id",
                "pack_id",
                "artifact_id",
                "artifact_version",
                "answer_digest",
                "correct",
                "score",
                "evidence_origin",
                "activity_kind",
                "scorer_id",
            },
        )
        self.assertEqual(
            result["attempt"]["schema_version"], "lumi.study-pack-attempt.v1"
        )
        self.assertEqual(set(result["result"]), {"correct", "score", "max_score"})
        self.assertEqual(
            set(result["learning_projection_writes"]),
            {"kt", "misconception", "today_plan", "review_schedule"},
        )
        self.assertFalse(any(result["learning_projection_writes"].values()))
        self.assertEqual(set(result["links"]), {"pack", "replay"})
        for citation in result["cited_source_context"]:
            self.assertEqual(
                set(citation),
                {
                    "field_pointer",
                    "span_id",
                    "locator_kind",
                    "locator_index",
                    "start_offset",
                    "end_offset",
                    "excerpt",
                },
            )
            self.assertLessEqual(len(citation["excerpt"]), 2_000)

    def learning_state_digest(self) -> str:
        # Initialize the existing learning and scheduling tables before taking the
        # baseline. Study Pack is required to remain outside every table below.
        self.request("GET", "/v1/health")
        self.request("GET", "/v1/review-schedule")
        tables = (
            "content_snapshots",
            "review_schedule_tasks",
            "schedule_command_results",
            "schedule_events",
            "schedule_migrations",
            "today_plan_tasks",
            "today_plans",
            "trace_events",
        )
        connection = sqlite3.connect(self.database)
        try:
            payload: dict[str, Any] = {}
            for table in tables:
                columns = [
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                ]
                rows = connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'
                ).fetchall()
                payload[table] = {"columns": columns, "rows": rows}
        finally:
            connection.close()
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()

    def test_capabilities_advertise_only_the_closed_study_pack_surface(self) -> None:
        health_status, health = self.request("GET", "/v1/health")
        self.assertEqual(health_status, 200)
        self.assertEqual(health["version"], "0.3.0")
        with urllib.request.urlopen(f"{self.base}/v1/health", timeout=5) as response:
            self.assertEqual(response.headers["Server"], "HermesSidecar/0.3")
        status, capabilities = self.request("GET", "/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["service_version"], "0.3.0")
        self.assertIn("local-cited-study-pack-v1", capabilities["features"])
        expected = {
            "study_pack_create": "POST /v1/study-packs",
            "study_packs": "GET /v1/study-packs",
            "study_pack": "GET /v1/study-packs/{pack_id}",
            "study_pack_command": "POST /v1/study-packs/{pack_id}/commands",
            "study_pack_citation": "GET /v1/study-packs/{pack_id}/citations/{span_id}",
            "study_pack_replay": "GET /v1/study-packs/{pack_id}/replay",
            "study_pack_item_launch": "GET /v1/study-pack-items/{artifact_id}/launch",
            "study_pack_item_attempt": "POST /v1/study-pack-items/{artifact_id}/attempts",
        }
        for name, route in expected.items():
            self.assertEqual(capabilities["endpoints"][name], route)
        self.assertNotIn("study_pack_import_path", capabilities["endpoints"])
        self.assertNotIn("ocr", capabilities["features"])
        self.assertNotIn("web-crawl", capabilities["features"])

    def test_frozen_sidecar_dispatches_the_isolated_pdf_worker_mode(self) -> None:
        with patch("hermes_service.cli.pdf_worker_main", return_value=7) as worker:
            self.assertEqual(cli_main(["--lumi-study-pack-pdf-worker"]), 7)
        worker.assert_called_once_with()

    def test_cli_attempt_origin_defaults_human_and_allows_only_internal_evaluation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                configured_study_pack_attempt_origin(),
                "human_local_interactive",
            )
        with patch.dict(
            os.environ,
            {INTERNAL_ATTEMPT_ORIGIN_ENV: "evaluation_fixture"},
            clear=True,
        ):
            self.assertEqual(
                configured_study_pack_attempt_origin(), "evaluation_fixture"
            )
        with patch.dict(
            os.environ,
            {INTERNAL_ATTEMPT_ORIGIN_ENV: "human_local_interactive"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                SystemExit, "invalid internal Study Pack attempt origin"
            ):
                configured_study_pack_attempt_origin()

    def test_cli_learning_evaluation_mode_is_explicit_and_private(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                configured_learning_attempt_origin(), "human_local_interactive"
            )
            self.assertFalse(
                configured_evaluation_projection(
                    attempt_origin="human_local_interactive"
                )
            )
        with patch.dict(
            os.environ,
            {
                INTERNAL_LEARNING_ATTEMPT_ORIGIN_ENV: "evaluation_fixture",
                INTERNAL_EVALUATION_PROJECTION_ENV: "1",
            },
            clear=True,
        ):
            origin = configured_learning_attempt_origin()
            self.assertEqual(origin, "evaluation_fixture")
            self.assertTrue(configured_evaluation_projection(attempt_origin=origin))
        with patch.dict(
            os.environ,
            {INTERNAL_EVALUATION_PROJECTION_ENV: "1"},
            clear=True,
        ):
            with self.assertRaisesRegex(SystemExit, "invalid internal evaluation"):
                configured_evaluation_projection(
                    attempt_origin="human_local_interactive"
                )

    def test_pasted_text_full_loop_survives_restart_without_learning_writes(self) -> None:
        baseline = self.learning_state_digest()
        status, created = self.create_pack()
        self.assertEqual(status, 201)
        self.assertRegex(created["pack_id"], PACK_ID)
        self.assertRegex(created["source"]["document_id"], DOCUMENT_ID)
        self.assertEqual(created["lifecycle"], "draft")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["source"]["input_kind"], "pasted_text")
        self.assertEqual(created["artifact_counts"]["study_pack.practice_item"], 3)
        self.assert_practice_artifacts_redacted(created)
        self.assertTrue(
            all(
                link["status"] == "unconfirmed_candidate"
                for link in created["candidate_skill_links"]
            )
        )
        self.assertEqual(self.learning_state_digest(), baseline)

        status, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(status, 200)
        self.assertEqual(set(listing), {"schema_version", "count", "items"})
        self.assertEqual(listing["schema_version"], "lumi.study-pack-list.v1")
        self.assertEqual(listing["count"], 1)
        self.assertEqual(
            set(listing["items"][0]),
            {
                "pack_id",
                "title",
                "lifecycle",
                "version",
                "created_at",
                "updated_at",
                "links",
            },
        )
        self.assertEqual(set(listing["items"][0]["links"]), {"self"})
        self.assertEqual(listing["items"][0]["pack_id"], created["pack_id"])
        listing_text = json.dumps(listing, ensure_ascii=False).lower()
        for private_key in ("answer", "explanation", "citations"):
            self.assertNotIn(private_key, listing_text)
        status, fetched = self.request(
            "GET", f"/v1/study-packs/{created['pack_id']}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(fetched["pack_id"], created["pack_id"])
        self.assert_practice_artifacts_redacted(fetched)

        launch_id = next(
            artifact["artifact_id"]
            for artifact in fetched["artifacts"]
            if artifact["artifact_type"] == "study_pack.practice_item"
        )
        self.assertRegex(launch_id, ARTIFACT_ID)
        note = next(
            artifact
            for artifact in fetched["artifacts"]
            if artifact["artifact_type"] == "study_pack.one_page_notes"
        )
        unpublished_span = note["content"]["citations"][0]["span_ref"]
        self.assert_error(
            self.request(
                "GET",
                f"/v1/study-packs/{created['pack_id']}/citations/{unpublished_span}",
            ),
            409,
            "artifact_not_published",
            forbidden=(self.sentences[0],),
        )
        self.assert_error(
            self.request("GET", f"/v1/study-pack-items/{launch_id}/launch"),
            409,
            "artifact_not_published",
        )

        status, reviewed = self.command(created, "request_review", "review-pack")
        self.assertEqual(status, 200)
        self.assertEqual(reviewed["lifecycle"], "review")
        self.assertTrue(reviewed["review"]["accepted"])
        self.assert_practice_artifacts_redacted(reviewed)
        self.assertTrue(
            all(
                ENTITY_ID.fullmatch(item["decision_id"])
                for item in reviewed["review"]["decision_refs"]
            )
        )
        status, published = self.command(reviewed, "publish", "publish-pack")
        self.assertEqual(status, 200)
        self.assertEqual(published["lifecycle"], "published")
        self.assert_practice_artifacts_redacted(published)
        self.assertEqual(self.learning_state_digest(), baseline)

        note = next(
            artifact
            for artifact in published["artifacts"]
            if artifact["artifact_type"] == "study_pack.one_page_notes"
        )
        span_id = note["content"]["citations"][0]["span_ref"]
        self.assertRegex(span_id, SPAN_ID)

        self.restart()
        status, citation = self.request(
            "GET",
            f"/v1/study-packs/{published['pack_id']}/citations/{span_id}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            set(citation),
            {
                "schema_version",
                "verified",
                "span_id",
                "document_id",
                "source_version",
                "normalized_source_sha256",
                "locator_kind",
                "locator_index",
                "start_offset",
                "end_offset",
                "slice_sha256",
                "excerpt",
                "links",
            },
        )
        self.assertEqual(citation["schema_version"], "lumi.source-citation.v1")
        self.assertEqual(set(citation["links"]), {"pack"})
        self.assertEqual(citation["span_id"], span_id)
        self.assertEqual(citation["excerpt"], self.sentences[0])
        self.assertTrue(citation["verified"])

        status, replay = self.request(
            "GET", f"/v1/study-packs/{published['pack_id']}/replay"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            set(replay),
            {
                "schema_version",
                "pack_id",
                "trace_verified",
                "projection_verified",
                "frame_count",
                "frames",
            },
        )
        self.assertEqual(replay["schema_version"], "lumi.study-pack-replay.v1")
        self.assertTrue(
            all(set(frame) == {"seq", "kind", "state"} for frame in replay["frames"])
        )
        self.assertTrue(replay["trace_verified"])
        self.assertTrue(replay["projection_verified"])
        self.assertGreaterEqual(replay["frame_count"], 3)
        replay_text = json.dumps(replay, ensure_ascii=False)
        self.assertNotIn(self.source_text, replay_text)
        self.assertNotIn(self.sentences[0], replay_text)

        status, current = self.request(
            "GET", f"/v1/study-packs/{published['pack_id']}"
        )
        self.assertEqual(status, 200)
        self.assert_practice_artifacts_redacted(current)
        self.assertEqual(current["attempt_history"], [])
        launch_id = next(
            artifact["artifact_id"]
            for artifact in current["artifacts"]
            if artifact["artifact_type"] == "study_pack.practice_item"
        )
        status, launch = self.request(
            "GET", f"/v1/study-pack-items/{launch_id}/launch"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            set(launch),
            {
                "schema_version",
                "pack_id",
                "pack_version",
                "artifact_id",
                "artifact_version",
                "item_kind",
                "prompt",
                "scorer",
                "activity_kind",
                "evidence_origin",
                "links",
            },
        )
        launch_text = json.dumps(launch, ensure_ascii=False).lower()
        for forbidden in (
            "answer",
            "explanation",
            "citation",
            self.sentences[0].lower(),
            self.source_text.lower(),
        ):
            self.assertNotIn(forbidden, launch_text)

        expected_answer = self.answer_for_launch(launch["prompt"])

        status, attempted = self.request(
            "POST",
            f"/v1/study-pack-items/{launch_id}/attempts",
            {
                "learner_answer": expected_answer,
                "expected_pack_version": launch["pack_version"],
                "expected_artifact_version": launch["artifact_version"],
                "command_id": opaque_command("answer-item"),
            },
        )
        self.assertEqual(status, 201)
        self.assert_attempt_result_closed(attempted)
        self.assertEqual(
            attempted["schema_version"], "lumi.study-pack-attempt-result.v1"
        )
        self.assertRegex(attempted["attempt"]["attempt_id"], ATTEMPT_ID)
        self.assertTrue(attempted["result"]["correct"])
        self.assertEqual(attempted["result"]["score"], 1.0)
        self.assertEqual(attempted["answer"], expected_answer)
        self.assertTrue(attempted["explanation"])
        self.assertEqual(
            attempted["attempt"]["evidence_origin"], "human_local_interactive"
        )
        self.assertEqual(
            attempted["attempt"]["activity_kind"], "within_pack_practice"
        )
        self.assertTrue(attempted["cited_source_context"])
        self.assertEqual(self.learning_state_digest(), baseline)

        status, history_pack = self.request(
            "GET", f"/v1/study-packs/{published['pack_id']}"
        )
        self.assertEqual(status, 200)
        self.assert_practice_artifacts_redacted(history_pack)
        self.assertEqual(len(history_pack["attempt_history"]), 1)
        history_entry = history_pack["attempt_history"][0]
        self.assertEqual(history_entry["prompt"], launch["prompt"])
        self.assertEqual(history_entry["learner_answer"], expected_answer)
        self.assertEqual(history_entry["answer"], expected_answer)
        self.assertEqual(
            history_entry["attempt"]["attempt_id"], attempted["attempt"]["attempt_id"]
        )
        self.assertEqual(self.learning_state_digest(), baseline)

        status, replay_after_attempt = self.request(
            "GET", f"/v1/study-packs/{published['pack_id']}/replay"
        )
        self.assertEqual(status, 200)
        serialized_replay = json.dumps(replay_after_attempt, ensure_ascii=False)
        self.assertNotIn(expected_answer, serialized_replay)

    def test_create_and_commands_are_closed_idempotent_and_conflict_safe(self) -> None:
        command_id = opaque_command("idempotent-create")
        status, created = self.create_pack(command_id=command_id)
        self.assertEqual(status, 201)
        status, replayed = self.create_pack(command_id=command_id)
        self.assertEqual(status, 201)
        self.assertEqual(replayed["pack_id"], created["pack_id"])
        self.assertTrue(replayed["idempotent_replay"])

        self.assert_error(
            self.create_pack(
                command_id=command_id,
                title="不同标题",
            ),
            409,
            "command_conflict",
        )
        self.assert_error(
            self.request(
                "POST",
                "/v1/study-packs",
                {
                    "title": "非法字段",
                    "command_id": opaque_command("unknown-field"),
                    "source": {"kind": "pasted_text", "text": self.source_text},
                    "pack_id": "client-selected-pack-id",
                },
            ),
            400,
            "invalid_body",
        )

        sensitive_command = SECRET_LIKE_OPENAI
        self.assert_error(
            self.command(
                created,
                "request_review",
                "ignored-sensitive-command",
                command_id=sensitive_command,
            ),
            400,
            "invalid_command_id",
            forbidden=(sensitive_command,),
        )
        _, unchanged = self.request(
            "GET", f"/v1/study-packs/{created['pack_id']}"
        )
        self.assertEqual(unchanged["version"], created["version"])
        self.assertEqual(unchanged["lifecycle"], "draft")

        status, reviewed = self.command(created, "request_review", "review-once")
        self.assertEqual(status, 200)
        status, repeated = self.command(
            created,
            "request_review",
            "ignored",
            command_id=opaque_command("review-once"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(repeated["pack_id"], reviewed["pack_id"])
        self.assertTrue(repeated["idempotent_replay"])
        self.assert_error(
            self.command(
                reviewed,
                "publish",
                "ignored",
                expected_version=reviewed["version"],
                command_id=opaque_command("review-once"),
            ),
            409,
            "command_conflict",
        )
        self.assert_error(
            self.command(
                reviewed,
                "publish",
                "stale-publish",
                expected_version=1,
            ),
            409,
            "stale_version",
        )
        self.assert_error(
            self.command(reviewed, "request_review", "invalid-transition"),
            409,
            "invalid_transition",
        )

    def test_concurrent_publish_has_one_winner_and_replays_after_restart(self) -> None:
        status, created = self.create_pack("concurrent-create")
        self.assertEqual(status, 201)
        status, reviewed = self.command(created, "request_review", "concurrent-review")
        self.assertEqual(status, 200)

        def publish(label: str) -> tuple[int, dict[str, Any]]:
            return self.command(reviewed, "publish", label)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, ("publish-a", "publish-b")))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        loser = next(payload for status, payload in results if status == 409)
        self.assertEqual(loser["error"]["code"], "stale_version")
        winner = next(payload for status, payload in results if status == 200)
        self.assertEqual(winner["lifecycle"], "published")

        self.restart()
        status, fetched = self.request("GET", f"/v1/study-packs/{winner['pack_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["version"], winner["version"])
        self.assertEqual(fetched["lifecycle"], "published")

    def test_source_failures_and_sensitive_identifiers_make_zero_writes(self) -> None:
        status, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 0)
        cases = (
            (
                {"kind": "pasted_text", "text": ""},
                "invalid_source_body",
                400,
            ),
            (
                {"kind": "unknown", "text": self.source_text},
                "invalid_source_body",
                400,
            ),
            (
                {"kind": "text_pdf", "pdf_base64": "***"},
                "invalid_source_body",
                400,
            ),
            (
                {
                    "kind": "text_pdf",
                    "pdf_base64": base64.b64encode(b"not-a-pdf").decode("ascii"),
                },
                "pdf_parse_failed",
                422,
            ),
            (
                {
                    "kind": "text_pdf",
                    "pdf_base64": base64.b64encode(
                        b"%PDF-1.7\n1 0 obj << /Encrypt 2 0 R >> endobj"
                    ).decode("ascii"),
                },
                "pdf_parse_failed",
                422,
            ),
            (
                {"kind": "pasted_text", "text": "字" * (512 * 1024)},
                "source_too_large",
                413,
            ),
        )
        for index, (source, code, expected_status) in enumerate(cases):
            with self.subTest(code=code, index=index):
                self.assert_error(
                    self.create_pack(f"invalid-source-{index}", source=source),
                    expected_status,
                    code,
                    forbidden=(self.source_text,),
                )

        invalid_commands = (
            "c_short",
            "15512345678",
            "110105199001011234",
            "550e8400-e29b-41d4-a716-446655440000",
            "learner@example.com",
            "/Users/local/private/source.pdf",
            SECRET_LIKE_OPENAI,
            SECRET_LIKE_GITHUB,
        )
        for index, command_id in enumerate(invalid_commands):
            with self.subTest(command_id=index):
                self.assert_error(
                    self.create_pack(
                        f"invalid-command-{index}",
                        command_id=command_id,
                    ),
                    400,
                    "invalid_command_id",
                    forbidden=(command_id, self.source_text),
                )
        _, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(listing["count"], 0)

    def test_sensitive_public_ids_are_rejected_before_database_creation(self) -> None:
        self.assertFalse(self.database.exists())
        sensitive_pack_id = urllib.parse.quote(
            "learner@example.com", safe=""
        )
        self.assert_error(
            self.request("GET", f"/v1/study-packs/{sensitive_pack_id}"),
            400,
            "invalid_pack_id",
            forbidden=("learner@example.com",),
        )
        self.assertFalse(self.database.exists())

        sensitive_command = SECRET_LIKE_OPENAI
        self.assert_error(
            self.create_pack(
                "prewrite-sensitive-command",
                command_id=sensitive_command,
            ),
            400,
            "invalid_command_id",
            forbidden=(sensitive_command, self.source_text),
        )
        self.assertFalse(self.database.exists())

    def test_encrypted_pdf_maps_to_stable_error_without_partial_write(self) -> None:
        self.restart(pdf_backend=EncryptedPdfBackend())
        source = {
            "kind": "text_pdf",
            "pdf_base64": base64.b64encode(b"%PDF-1.7\n% encrypted fixture").decode(
                "ascii"
            ),
        }
        self.assert_error(
            self.create_pack("encrypted-pdf", source=source),
            422,
            "pdf_encrypted_unsupported",
        )
        _, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(listing["count"], 0)

    def test_malformed_json_and_sensitive_route_ids_fail_closed(self) -> None:
        self.assert_error(
            self.request("POST", "/v1/study-packs", raw=b"{"),
            400,
            "invalid_json",
        )
        self.assert_error(
            self.request("POST", "/v1/study-packs", body=[]),
            400,
            "invalid_body",
        )
        self.assert_error(
            self.request(
                "POST",
                "/v1/study-packs",
                {
                    "title": "嵌套字段必须关闭",
                    "command_id": opaque_command("nested-unknown"),
                    "source": {
                        "kind": "pasted_text",
                        "text": self.source_text,
                        "filename": "/Users/local/private.pdf",
                    },
                },
            ),
            400,
            "invalid_source_body",
            forbidden=(self.source_text, "/Users/local/private.pdf"),
        )

        sensitive_ids = (
            "15512345678",
            "110105199001011234",
            "550e8400-e29b-41d4-a716-446655440000",
            "learner@example.com",
            "/Users/local/private.pdf",
            SECRET_LIKE_OPENAI,
            SECRET_LIKE_GITHUB,
        )
        for index, sensitive_id in enumerate(sensitive_ids):
            with self.subTest(identifier=index):
                quoted = urllib.parse.quote(sensitive_id, safe="")
                self.assert_error(
                    self.request("GET", f"/v1/study-packs/{quoted}"),
                    400,
                    "invalid_pack_id",
                    forbidden=(sensitive_id,),
                )
                self.assert_error(
                    self.request(
                        "GET", f"/v1/study-pack-items/{quoted}/launch"
                    ),
                    400,
                    "invalid_artifact_id",
                    forbidden=(sensitive_id,),
                )
        _, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(listing["count"], 0)

    def test_scanned_pdf_maps_to_ocr_required_without_partial_write(self) -> None:
        self.restart(pdf_backend=EmptyTextPdfBackend())
        source = {
            "kind": "text_pdf",
            "pdf_base64": base64.b64encode(b"%PDF-1.7\n% image-only fixture").decode("ascii"),
        }
        self.assert_error(
            self.create_pack("scanned-pdf", source=source),
            422,
            "pdf_text_unavailable_ocr_required",
        )
        _, listing = self.request("GET", "/v1/study-packs")
        self.assertEqual(listing["count"], 0)

    def test_text_pdf_union_uses_page_citations_over_real_http(self) -> None:
        pages = (
            "\n".join(self.sentences[:3]),
            "\n".join(self.sentences[3:]),
        )
        self.restart(pdf_backend=TextLayerPdfBackend(pages))
        pdf_bytes = b"%PDF-1.7\n% local text-layer fixture"
        status, created = self.create_pack(
            "text-pdf-create",
            source={
                "kind": "text_pdf",
                "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["source"]["input_kind"], "text_pdf")
        self.assertEqual(created["source"]["media_type"], "application/pdf")
        self.assertEqual(created["source"]["locator_count"], 2)
        self.assertEqual(created["source"]["parser_name"], "qa-text-layer-parser")
        self.assert_practice_artifacts_redacted(created)

        _, reviewed = self.command(created, "request_review", "text-pdf-review")
        status, published = self.command(reviewed, "publish", "text-pdf-publish")
        self.assertEqual(status, 200)
        note = next(
            artifact
            for artifact in published["artifacts"]
            if artifact["artifact_type"] == "study_pack.one_page_notes"
        )
        span_id = note["content"]["citations"][0]["span_ref"]
        status, citation = self.request(
            "GET",
            f"/v1/study-packs/{published['pack_id']}/citations/{span_id}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(citation["locator_kind"], "page")
        self.assertEqual(citation["locator_index"], 1)
        self.assertEqual(citation["excerpt"], self.sentences[0])
        self.assertTrue(citation["verified"])

    def test_insufficient_frozen_source_is_quarantined_and_cannot_transition(self) -> None:
        baseline = self.learning_state_digest()
        short_source = "只有一条可引用但不足以生成完整学习包的材料。"
        status, quarantined = self.create_pack(
            "insufficient-source",
            source={"kind": "pasted_text", "text": short_source},
        )
        self.assertEqual(status, 201)
        self.assertEqual(quarantined["lifecycle"], "quarantined")
        self.assertEqual(
            quarantined["quarantine_reason"], "source_insufficient_for_pack"
        )
        self.assertEqual(sum(quarantined["artifact_counts"].values()), 0)
        self.assertEqual(quarantined["artifacts"], [])
        self.assertEqual(self.learning_state_digest(), baseline)
        self.assert_error(
            self.command(
                quarantined,
                "request_review",
                "quarantined-review",
            ),
            409,
            "invalid_transition",
            forbidden=(short_source,),
        )
        self.restart()
        status, fetched = self.request(
            "GET", f"/v1/study-packs/{quarantined['pack_id']}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(fetched["lifecycle"], "quarantined")

    def test_study_pack_route_has_12_mib_limit_without_expanding_other_routes(self) -> None:
        # This body is above the existing 64 KiB default but below 12 MiB. It
        # reaches Study Pack source validation and therefore returns source_too_large.
        medium = "\n\n".join(
            f"第 {index} 条材料说明：" + ("本地学习资料" * 100) + "。"
            for index in range(1, 101)
        )
        status, accepted = self.create_pack(
            "route-specific-limit",
            source={"kind": "pasted_text", "text": medium},
        )
        self.assertEqual(status, 201)
        self.assertEqual(accepted["source"]["byte_count"], len(medium.encode("utf-8")))
        self.assert_practice_artifacts_redacted(accepted)

        self.assert_error(
            self.request_with_declared_length(
                "/v1/study-packs", 12 * 1024 * 1024 + 1
            ),
            413,
            "payload_too_large",
        )

        self.assert_error(
            self.request_with_declared_length("/v1/attempts", 64 * 1024 + 1),
            413,
            "payload_too_large",
        )

    def test_item_attempt_is_closed_idempotent_and_requires_published_item(self) -> None:
        status, created = self.create_pack("attempt-closed-create")
        self.assertEqual(status, 201)
        item_id = next(
            artifact["artifact_id"]
            for artifact in created["artifacts"]
            if artifact["artifact_type"] == "study_pack.practice_item"
        )
        self.assert_error(
            self.request(
                "POST",
                f"/v1/study-pack-items/{item_id}/attempts",
                {
                    "learner_answer": self.sentences[0],
                    "expected_pack_version": created["version"],
                    "expected_artifact_version": 1,
                    "command_id": opaque_command("draft-attempt"),
                },
            ),
            409,
            "artifact_not_published",
            forbidden=(self.sentences[0],),
        )

        reviewed_status, reviewed = self.command(
            created, "request_review", "attempt-closed-review"
        )
        self.assertEqual(reviewed_status, 200)
        publish_status, published = self.command(
            reviewed, "publish", "attempt-closed-publish"
        )
        self.assertEqual(publish_status, 200)
        item = next(
            artifact
            for artifact in published["artifacts"]
            if artifact["artifact_id"] == item_id
        )
        command_id = opaque_command("idempotent-answer")
        body = {
            "learner_answer": self.sentences[0],
            "expected_pack_version": published["version"],
            "expected_artifact_version": item["artifact_version"],
            "command_id": command_id,
        }
        sensitive_command = SECRET_LIKE_GITHUB
        self.assert_error(
            self.request(
                "POST",
                f"/v1/study-pack-items/{item_id}/attempts",
                {**body, "command_id": sensitive_command},
            ),
            400,
            "invalid_command_id",
            forbidden=(sensitive_command, self.sentences[0]),
        )
        status, first = self.request(
            "POST", f"/v1/study-pack-items/{item_id}/attempts", body
        )
        self.assertEqual(status, 201)
        self.assert_attempt_result_closed(first)
        status, repeated = self.request(
            "POST", f"/v1/study-pack-items/{item_id}/attempts", body
        )
        self.assertEqual(status, 201)
        self.assert_attempt_result_closed(repeated)
        self.assertEqual(
            repeated["attempt"]["attempt_id"], first["attempt"]["attempt_id"]
        )
        self.assertTrue(repeated["idempotent_replay"])

        self.assert_error(
            self.request(
                "POST",
                f"/v1/study-pack-items/{item_id}/attempts",
                {**body, "learner_answer": "不同答案"},
            ),
            409,
            "command_conflict",
        )
        self.assert_error(
            self.request(
                "POST",
                f"/v1/study-pack-items/{item_id}/attempts",
                {**body, "extra": True, "command_id": opaque_command("extra-answer")},
            ),
            400,
            "invalid_body",
        )
        self.assert_error(
            self.request(
                "POST",
                f"/v1/study-pack-items/{item_id}/attempts",
                {
                    **body,
                    "expected_pack_version": 99,
                    "command_id": opaque_command("stale-answer"),
                },
            ),
            409,
            "stale_version",
        )

    def test_evaluation_attempt_origin_is_private_configuration_not_request_data(self) -> None:
        self.restart(attempt_evidence_origin="evaluation_fixture")
        published = self.publish_pack()
        item = next(
            artifact
            for artifact in published["artifacts"]
            if artifact["artifact_type"] == "study_pack.practice_item"
        )
        status, launch = self.request(
            "GET", f"/v1/study-pack-items/{item['artifact_id']}/launch"
        )
        self.assertEqual(status, 200)
        self.assertEqual(launch["evidence_origin"], "evaluation_fixture")
        answer = self.answer_for_launch(launch["prompt"])
        body = {
            "learner_answer": answer,
            "expected_pack_version": launch["pack_version"],
            "expected_artifact_version": launch["artifact_version"],
            "command_id": opaque_command("evaluation-answer"),
        }
        self.assert_error(
            self.request(
                "POST",
                launch["links"]["attempts"],
                {**body, "evidence_origin": "human_local_interactive"},
            ),
            400,
            "invalid_body",
        )
        status, attempted = self.request(
            "POST", launch["links"]["attempts"], body
        )
        self.assertEqual(status, 201)
        self.assertEqual(
            attempted["attempt"]["evidence_origin"], "evaluation_fixture"
        )
        status, detail = self.request(
            "GET", f"/v1/study-packs/{published['pack_id']}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(detail["attempt_history"], [])
        connection = sqlite3.connect(self.database)
        try:
            origins = connection.execute(
                "SELECT evidence_origin, COUNT(*) FROM study_pack_attempts "
                "GROUP BY evidence_origin"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(origins, [("evaluation_fixture", 1)])
        with self.assertRaises(ValueError):
            SidecarApplication(
                self.database,
                study_pack_attempt_evidence_origin="synthetic",
            )


if __name__ == "__main__":
    unittest.main()
