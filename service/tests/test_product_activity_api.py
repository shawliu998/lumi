from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication
from hermes_service.catalog import ProductActivityCatalog


def _payload() -> dict[str, Any]:
    return {
        "schema_version": "lumi.xingce-local-payload.v0",
        "release_id": "p031-test-v1",
        "distribution": "local_only",
        "items": [
            {
                "question_id": "q_product_first",
                "diagnostic_role": "first_answer",
                "material_text": "某指标本期为 120，同比增长 20%。",
                "stem_text": "上期约为多少？",
                "options": [
                    {"label": "A", "text": "96", "is_correct": False},
                    {"label": "B", "text": "100", "is_correct": True},
                    {"label": "C", "text": "120", "is_correct": False},
                    {"label": "D", "text": "144", "is_correct": False},
                ],
                "answer_labels": "B",
                "correct_option": "B",
                "explanation_text": "120 / 1.2 = 100",
                "candidate_skills": [{"skill_id": "private.candidate"}],
                "source": {
                    "content_signature": "content-first-v1",
                    "paper_title": "测试题本",
                    "year": 2026,
                    "question_no": 1,
                    "source_site": "local-test",
                    "source_url": "https://example.invalid/source",
                },
            },
            {
                "question_id": "q_product_transfer",
                "diagnostic_role": "independent_transfer",
                "material_text": "另一个材料。",
                "stem_text": "另一道题？",
                "options": [
                    {"label": "A", "text": "一"},
                    {"label": "B", "text": "二"},
                    {"label": "C", "text": "三"},
                    {"label": "D", "text": "四"},
                ],
                "answer_labels": "A",
                "explanation_text": "私有解析",
                "source": {
                    "content_signature": "content-transfer-v1",
                    "paper_title": "测试题本",
                    "year": 2026,
                    "question_no": 2,
                    "source_site": "local-test",
                    "source_url": "https://example.invalid/source",
                },
            },
        ],
    }


class _FakeProductActivity:
    def public_view(self) -> dict[str, Any]:
        items = _payload()["items"]
        public_items = []
        for item in items:
            public_items.append(
                {
                    key: value
                    for key, value in item.items()
                    if key
                    in {
                        "question_id",
                        "diagnostic_role",
                        "material_text",
                        "stem_text",
                        "options",
                        "source",
                    }
                }
            )
            public_items[-1]["options"] = [
                {"label": row["label"], "text": row["text"]}
                for row in item["options"]
            ]
        return {
            "schema_version": "lumi.product-activity-public.v1",
            "activity_id": "runtime-product-test",
            "release_id": "p031-test-v1",
            "first_answer": public_items[0],
            "independent_transfer": public_items[1],
        }

    def to_runtime_fixture(self) -> dict[str, Any]:
        return {
            "schema_version": "hermes.domain-fixture.v1",
            "fixture_id": "runtime-product-test",
            "domain": "xingce",
            "path": "data_analysis",
            "execution": {"connectivity": "local", "cloud_calls_expected": 0},
            "provenance": {
                "content_origin": "local_versioned_export",
                "distribution": "local_only",
                "first_item": {
                    "question_id": "q_product_first",
                    "content_signature": "content-first-v1",
                },
                "transfer_item": {
                    "question_id": "q_product_transfer",
                    "content_signature": "content-transfer-v1",
                },
            },
            "diagnosis": {
                "semantics": "ranked_unconfirmed_hypotheses",
                "candidate_causes": [
                    {
                        "cause_id": "candidate",
                        "synthetic_prior": 0.5,
                        "is_ground_truth": False,
                    }
                ],
            },
        }


def _catalog() -> ProductActivityCatalog:
    return ProductActivityCatalog(activities=(_FakeProductActivity(),))


class ProductActivityCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_public_projection_is_built_without_private_scoring_fields(self) -> None:
        catalog = _catalog()
        projected = catalog.get("q_product_first")
        serialized = json.dumps(projected, ensure_ascii=False).lower()
        for forbidden in (
            "answer_labels",
            "correct_option",
            "explanation_text",
            "is_correct",
            "candidate_skills",
            "private.candidate",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(projected["stem_text"], "上期约为多少？")
        self.assertEqual(projected["item_id"], "q_product_first")
        self.assertEqual(projected["content_signature"], "content-first-v1")
        self.assertEqual(projected["options"][1], {"label": "B", "text": "100"})

    def test_missing_local_payload_is_an_empty_supported_catalog(self) -> None:
        catalog = ProductActivityCatalog(self.root / "missing.json")
        self.assertEqual(catalog.list(), [])

    def test_filters_preserve_stable_activity_order(self) -> None:
        catalog = _catalog()
        first = catalog.list(diagnostic_role="first_answer")
        self.assertEqual([item["activity_id"] for item in first], ["q_product_first"])
        self.assertEqual(len(catalog.list(release_id="p031-test-v1")), 2)

    def test_launchable_fixture_lookup_uses_runtime_fixture_id(self) -> None:
        catalog = ProductActivityCatalog()
        if not catalog.list():
            self.skipTest("ignored local Xingce payload has not been generated")
        first = catalog.list(diagnostic_role="first_answer")
        fixture = catalog.resolve_fixture(first[0]["activity_id"])
        resolved = catalog.resolve_launchable_fixture(fixture["fixture_id"])
        self.assertEqual(resolved["fixture_id"], fixture["fixture_id"])
        self.assertEqual(
            resolved["provenance"]["content_origin"], "local_versioned_export"
        )
        with self.assertRaises(KeyError):
            catalog.resolve_launchable_fixture("xingce.data-analysis.growth-rate.synthetic-01")

    def test_default_catalog_resolves_only_bound_first_answer_when_local_payload_exists(self) -> None:
        catalog = ProductActivityCatalog()
        if not catalog.list():
            self.skipTest("ignored local Xingce payload has not been generated")
        first = catalog.list(diagnostic_role="first_answer")
        transfer = catalog.list(diagnostic_role="independent_transfer")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(transfer), 1)
        fixture = catalog.resolve_fixture(first[0]["activity_id"])
        self.assertEqual(
            fixture["provenance"]["transfer_item"]["question_id"],
            transfer[0]["activity_id"],
        )
        self.assertEqual(
            fixture["provenance"]["transfer_item"]["content_signature"],
            transfer[0]["content_signature"],
        )
        with self.assertRaises(KeyError):
            catalog.resolve_fixture(transfer[0]["activity_id"])


class ProductActivityHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        application = SidecarApplication(
            self.root / "sidecar.sqlite3",
            product_activity_catalog=_catalog(),
        )
        self.server = create_server(application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        return self.request("GET", path)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            return response.status, json.loads(response.read())
        finally:
            response.close()

    def test_human_attempt_rejects_legacy_scenario_fixture(self) -> None:
        status, error = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.7,
                "response_time_seconds": 12,
            },
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "product_activity_required")
        _, health = self.get("/v1/health")
        self.assertEqual(health["run_count"], 0)

    def test_list_detail_and_capabilities_are_safe(self) -> None:
        status, listing = self.get(
            "/v1/product-activities?diagnostic_role=first_answer"
        )
        self.assertEqual(status, 200)
        self.assertEqual(listing["count"], 1)
        detail_status, detail = self.get(
            "/v1/product-activities/q_product_first"
        )
        self.assertEqual(detail_status, 200)
        self.assertEqual(detail, listing["items"][0])
        serialized = json.dumps({"listing": listing, "detail": detail}).lower()
        self.assertNotIn("answer_labels", serialized)
        self.assertNotIn("correct_option", serialized)
        self.assertNotIn("explanation_text", serialized)
        self.assertNotIn("is_correct", serialized)

        _, capabilities = self.get("/v1/capabilities")
        self.assertEqual(capabilities["scenario_count"], 42)
        self.assertEqual(capabilities["product_activity_count"], 2)

    def test_unknown_activity_and_query_fail_closed(self) -> None:
        status, missing = self.get("/v1/product-activities/not-present")
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["code"], "product_activity_not_found")
        status, invalid = self.get("/v1/product-activities?answer_labels=B")
        self.assertEqual(status, 400)
        self.assertEqual(invalid["error"]["code"], "invalid_query")


class RealProductActivityAttemptHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        if not ProductActivityCatalog().list():
            self.skipTest("ignored local Xingce payload has not been generated")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.application = SidecarApplication(
            self.root / "sidecar.sqlite3",
            attempt_evidence_origin="evaluation_fixture",
        )
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        if not hasattr(self, "server"):
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            return response.status, json.loads(response.read())
        finally:
            response.close()

    def test_real_first_answer_then_probe_binds_unseen_transfer_without_kt(self) -> None:
        _, first_listing = self.request(
            "GET",
            "/v1/product-activities?diagnostic_role=first_answer",
        )
        _, transfer_listing = self.request(
            "GET",
            "/v1/product-activities?diagnostic_role=independent_transfer",
        )
        self.assertEqual(first_listing["count"], 1)
        self.assertEqual(transfer_listing["count"], 1)
        first = first_listing["items"][0]
        transfer = transfer_listing["items"][0]
        self.assertNotEqual(first["item_id"], transfer["item_id"])
        self.assertNotEqual(
            first["content_signature"], transfer["content_signature"]
        )

        status, initial = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": first["activity_id"],
                "response": "A",
                "confidence": 0.5,
                "response_time_seconds": 12,
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(initial["state"], "awaiting_probe")
        self.assertIsNone(initial["mastery_update"])

        status, after_probe = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": initial["state_version"],
                "expected_state": initial["state"],
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "response": "增长量除以基期量",
                "confidence": 0.6,
                "response_time_seconds": 10,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_probe["state"], "awaiting_verification")
        self.assertIsNone(after_probe["mastery_update"])
        binding = after_probe["teaching"]["independent_verification_item"]
        self.assertEqual(binding["item_id"], transfer["item_id"])
        self.assertEqual(
            binding["content_signature"], transfer["content_signature"]
        )
        self.assertEqual(binding["novelty_status"], "unseen_parallel_item")

        serialized = json.dumps(
            {"initial": initial, "after_probe": after_probe},
            ensure_ascii=False,
        ).lower()
        for forbidden in (
            '"answer_labels"',
            '"correct_option"',
            '"correct_answer"',
            '"explanation_text"',
            '"is_correct"',
        ):
            self.assertNotIn(forbidden, serialized)
        _, skills = self.request("GET", "/v1/skills/report")
        self.assertEqual(skills["skill_count"], 0)
        self.assertEqual(skills["items"], [])


if __name__ == "__main__":
    unittest.main()
