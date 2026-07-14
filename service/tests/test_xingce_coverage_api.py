from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication


class XingceCoverageApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.application = SidecarApplication(Path(self.temporary.name) / "sidecar.sqlite3")
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path: str) -> tuple[int, dict]:
        port = self.server.server_address[1]
        request = Request(f"http://127.0.0.1:{port}{path}")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_catalog_exposes_only_status_and_does_not_claim_unregistered_packs_are_usable(self) -> None:
        status, payload = self.request("/v1/xingce/coverage")
        self.assertEqual(status, 200)
        self.assertEqual(payload["schema_version"], "lumi.xingce-coverage-catalog.v1")
        self.assertTrue(payload["local_only"])
        self.assertEqual(payload["summary"]["total_subtypes"], 31)
        self.assertEqual(payload["summary"]["released_subtypes"], 31)
        self.assertEqual(payload["summary"]["reviewed_release_ready_subtypes"], 0)
        self.assertEqual(payload["summary"]["planned_subtypes"], 0)
        self.assertTrue(payload["summary"]["content_release_ready"])
        self.assertEqual(payload["summary"]["available_subtypes"], 0)
        self.assertTrue(payload["summary"]["is_complete"])
        self.assertEqual(len(payload["items"]), 31)
        available = [item for item in payload["items"] if item["availability"] == "available"]
        self.assertEqual(available, [])
        self.assertTrue(all("misconception_dimensions" not in item for item in payload["items"]))
        self.assertTrue(all("content_requirements" not in item for item in payload["items"]))
        planned = [item for item in payload["items"] if item["availability"] == "planned"]
        self.assertTrue(all(item["launch"] is None for item in planned))
        self.assertTrue(all(item["unavailable_reason"] == "local_reviewed_pack_not_registered" for item in planned))
        self.assertEqual({item["content_status"] for item in planned}, {"released"})

    def test_catalog_is_declared_in_capabilities_and_rejects_query_parameters(self) -> None:
        status, capabilities = self.request("/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["endpoints"]["xingce_coverage"], "GET /v1/xingce/coverage")
        self.assertIn("xingce-coverage-catalog-v1", capabilities["features"])
        status, error = self.request("/v1/xingce/coverage?module=verbal")
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "invalid_query")


if __name__ == "__main__":
    unittest.main()
