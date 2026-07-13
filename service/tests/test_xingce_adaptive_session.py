from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hermes_domains.xingce_coverage import load_coverage_matrix
from xingce_adaptive_fixtures import documents_for
from hermes_domains.xingce_adaptive_pack import record_sha256, reviewed_manifest_sha256
from hermes_service.xingce_adaptive_session import XingceAdaptiveSessionConfig, XingceAdaptiveSessionService
from hermes_service.application import SidecarApplication
from hermes_service.api import create_server


def reviewed_root(root: Path) -> Path:
    subtype = next(row for row in load_coverage_matrix()["subtypes"] if row["id"] == "xingce.verbal.logical_cloze")
    manifest, records, skills, taxonomy = documents_for(subtype)
    manifest.update({"status": "release_ready", "release_ready": True, "runtime_registration": "allowed_after_human_review"})
    manifest["rights"]["distribution"] = "release_distribution_allowed"
    manifest["human_review_gate"] = {"required": True, "production_load_allowed": True, "review_attestations": [
        {"review_kind": "logic", "status": "approved", "reviewer_id": "logic-reviewer", "reviewed_at": "2026-07-13", "manifest_sha256": "pending"},
        {"review_kind": "editorial_rights", "status": "approved", "reviewer_id": "rights-reviewer", "reviewed_at": "2026-07-13", "manifest_sha256": "pending"},
    ]}
    for document in (records, skills, taxonomy): document["review_status"] = "release_ready"
    for record in records["records"]:
        record["review_status"] = "release_ready"; record["record_sha256"] = record_sha256(record)
    for name, payload in (("records.json", records), ("skill-graph.json", skills), ("misconceptions.json", taxonomy)):
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
        (root / name).write_bytes(data)
        next(item for item in manifest["artifacts"] if item["path"] == name)["sha256"] = hashlib.sha256(data).hexdigest()
    evidence = {"schema_version": "lumi.xingce-review-evidence.v1", "manual_review_workbook": {"name": "evaluation-fixture.xlsx", "sha256": "a" * 64}, "reviewer_attestations": manifest["human_review_gate"]["review_attestations"]}
    data = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2).encode()
    (root / "review-evidence.json").write_bytes(data)
    manifest["artifacts"].append({"path": "review-evidence.json", "sha256": hashlib.sha256(data).hexdigest()})
    digest = reviewed_manifest_sha256(manifest)
    for attestation in manifest["human_review_gate"]["review_attestations"]:
        attestation["manifest_sha256"] = digest
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


class XingceAdaptiveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); pack = Path(self.temp.name) / "pack"; pack.mkdir()
        reviewed_root(pack)
        self.service = XingceAdaptiveSessionService(Path(self.temp.name) / "state.sqlite3", reviewed_pack_root=pack, config=XingceAdaptiveSessionConfig(namespace_id="eval:xingce-test", evidence_origin="evaluation_fixture"))

    def tearDown(self) -> None: self.temp.cleanup()

    def test_independent_transfer_is_the_only_kt_commit_path_and_replay_verifies(self) -> None:
        workspace = self.service.workspace(); self.assertEqual(workspace["entry_items"][0]["record_id"], "D01")
        entry = self.service.start(entry_record_id="D01", selected_response="B", confidence="high", elapsed_seconds=8, command_id="c_xingce_entry")
        self.assertEqual(entry["candidate_causes"][0]["status"], "unconfirmed")
        self.assertEqual(entry["candidate_causes"][0]["label"], "候选一")
        probe = self.service.answer_probe(session_id=entry["session_id"], expected_version=1, selected_response="A", confidence="medium", elapsed_seconds=7, command_id="c_xingce_probe")
        self.assertEqual(probe["probe"]["evidence_updates"][0]["label"], "候选一")
        completed = self.service.answer_transfer(session_id=entry["session_id"], expected_version=2, selected_response="A", confidence="high", elapsed_seconds=9, command_id="c_xingce_transfer")
        self.assertTrue(completed["state_update"]["eligible"])
        self.assertEqual(completed["state_update"]["receipts"][0]["state_delta"]["commit_status"], "committed")
        self.assertEqual(completed["review_task"]["kind"], "delayed_retention")
        self.assertEqual(
            self.service.answer_transfer(session_id=entry["session_id"], expected_version=2, selected_response="A", confidence="high", elapsed_seconds=9, command_id="c_xingce_transfer"),
            completed,
        )
        self.assertTrue(self.service.replay(entry["session_id"])["trace_verified"])

    def test_sidecar_registers_only_the_bound_reviewed_subtype(self) -> None:
        application = SidecarApplication(
            Path(self.temp.name) / "http.sqlite3",
            attempt_evidence_origin="evaluation_fixture",
            evaluation_projection_enabled=True,
            xingce_adaptive_session_services={"xingce.verbal.logical_cloze": self.service},
        )
        self.assertIn("xingce-adaptive-session-v1", application.capabilities()["features"])
        self.assertTrue(application.xingce_adaptive_workspace("xingce.verbal.logical_cloze")["available"])
        with self.assertRaises(Exception):
            application.xingce_adaptive_workspace("xingce.judgment.definition")
        with self.assertRaisesRegex(ValueError, "released coverage row"):
            SidecarApplication(
                Path(self.temp.name) / "production.sqlite3",
                xingce_adaptive_session_services={"xingce.verbal.logical_cloze": self.service},
            )

    def test_http_contract_runs_the_evaluation_fixture_without_accepting_judgment_only_fields(self) -> None:
        """HTTP checks use an isolated eval namespace, never a product learner."""
        application = SidecarApplication(
            Path(self.temp.name) / "http.sqlite3",
            attempt_evidence_origin="evaluation_fixture",
            evaluation_projection_enabled=True,
            xingce_adaptive_session_services={"xingce.verbal.logical_cloze": self.service},
        )
        server = create_server(application, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subtype = "xingce.verbal.logical_cloze"
            status, workspace = self.http(server, "GET", f"/v1/xingce/adaptive/{subtype}/workspace")
            self.assertEqual(status, 200)
            self.assertNotIn("correct_option", workspace["entry_items"][0])
            status, started = self.http(server, "POST", f"/v1/xingce/adaptive/{subtype}/sessions", {
                "entry_record_id": "D01", "selected_response": "B", "confidence": "high", "elapsed_seconds": 8, "command_id": "c_" + "A" * 40,
            })
            self.assertEqual(status, 201)
            status, invalid = self.http(server, "POST", f"/v1/xingce/adaptive/{subtype}/sessions/{started['session_id']}/probe", {
                "expected_version": 1, "expected_stage": "awaiting_probe", "selected_response": "A", "confidence": "medium", "elapsed_seconds": 7, "command_id": "c_" + "B" * 40,
            })
            self.assertEqual(status, 400)
            self.assertEqual(invalid["error"]["code"], "invalid_body")
            status, probe = self.http(server, "POST", f"/v1/xingce/adaptive/{subtype}/sessions/{started['session_id']}/probe", {
                "expected_version": 1, "selected_response": "A", "confidence": "medium", "elapsed_seconds": 7, "command_id": "c_" + "B" * 40,
            })
            self.assertEqual(status, 200)
            self.assertEqual(probe["stage"], "awaiting_transfer")
            status, completed = self.http(server, "POST", f"/v1/xingce/adaptive/{subtype}/sessions/{started['session_id']}/transfer", {
                "expected_version": 2, "selected_response": "A", "confidence": "high", "elapsed_seconds": 9, "command_id": "c_" + "C" * 40,
            })
            self.assertEqual(status, 200)
            self.assertEqual(completed["stage"], "completed")
            status, replay = self.http(server, "GET", f"/v1/xingce/adaptive/{subtype}/sessions/{started['session_id']}/replay")
            self.assertEqual(status, 200)
            self.assertTrue(replay["trace_verified"])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    @staticmethod
    def http(server: object, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        port = server.server_address[1]  # type: ignore[attr-defined]
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(f"http://127.0.0.1:{port}{path}", data=body, method=method)
        if body is not None: request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()


if __name__ == "__main__": unittest.main()
