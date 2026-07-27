import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.datahub_adapter import DataHubUnavailable
from app.main import create_app
from app.mcp_context import ContextUnavailable
from app.models import DecisionContext


class SuccessfulAdapter:
    def __init__(self, _config):
        pass

    def healthcheck(self) -> bool:
        return True

    def create_decision_document(
        self, *, decision_id: str, title: str, summary: str, related_assets: list[str]
    ) -> str:
        assert title
        assert "## Evidence" in summary
        assert len(related_assets) == 2
        return f"urn:li:document:decisiongraph-{decision_id}"


class FlakyAdapter(SuccessfulAdapter):
    attempts = 0

    def create_decision_document(
        self, *, decision_id: str, title: str, summary: str, related_assets: list[str]
    ) -> str:
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise DataHubUnavailable("temporary outage")
        return super().create_decision_document(
            decision_id=decision_id,
            title=title,
            summary=summary,
            related_assets=related_assets,
        )


class TimeoutAdapter(SuccessfulAdapter):
    def create_decision_document(self, **_kwargs) -> str:
        raise TimeoutError("socket timed out")


class FalseHealthAdapter(SuccessfulAdapter):
    def healthcheck(self) -> bool:
        return False


class MCPContextProvider:
    calls = 0

    async def fetch_reorder_context(self) -> DecisionContext:
        type(self).calls += 1
        return DecisionContext(
            source="datahub_mcp_server",
            tools=["get_entities", "list_schema_fields"],
            facts=[
                f"Fresh MCP context retrieval {type(self).calls}.",
                "Three governed Northeast reorder candidates were confirmed.",
            ],
            snapshot={"retrieval": type(self).calls},
        )


class FailingContextProvider:
    async def fetch_reorder_context(self) -> DecisionContext:
        raise ContextUnavailable("MCP context unavailable")


class DecisionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "decisiongraph.db"
        self.previous_url = os.environ.pop("DATAHUB_GMS_URL", None)
        self.previous_mcp_enabled = os.environ.pop(
            "DATAHUB_MCP_ENABLED", None
        )

    def tearDown(self) -> None:
        if self.previous_url is not None:
            os.environ["DATAHUB_GMS_URL"] = self.previous_url
        else:
            os.environ.pop("DATAHUB_GMS_URL", None)
        if self.previous_mcp_enabled is not None:
            os.environ["DATAHUB_MCP_ENABLED"] = self.previous_mcp_enabled
        else:
            os.environ.pop("DATAHUB_MCP_ENABLED", None)
        self.temp_dir.cleanup()

    def test_offline_revalidation_creates_replacement_and_supersedes_original(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        created = client.post("/api/v1/decisions/run")
        self.assertEqual(created.status_code, 201)
        decision_id = created.json()["id"]

        approved = client.post(f"/api/v1/decisions/{decision_id}/approve")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "APPROVED")
        self.assertEqual(
            approved.json()["projection_status"], "NOT_CONFIGURED"
        )
        self.assertEqual(
            client.post(f"/api/v1/decisions/{decision_id}/approve").status_code,
            409,
        )

        restarted = TestClient(create_app(db_path=self.db_path))
        persisted = restarted.get(f"/api/v1/decisions/{decision_id}").json()
        self.assertEqual(persisted["status"], "APPROVED")

        asset_urn = persisted["dependencies"][0]["asset_urn"]
        impacted = restarted.post(
            "/api/v1/events/invalidation",
            json={"asset_urn": asset_urn, "event_type": "DATASET_STALE"},
        )
        self.assertEqual(impacted.status_code, 200)
        self.assertEqual(impacted.json()[0]["status"], "REVALIDATION_REQUIRED")

        replacement = restarted.post(f"/api/v1/decisions/{decision_id}/revalidate")
        self.assertEqual(replacement.status_code, 200)
        replacement_id = replacement.json()["id"]
        self.assertEqual(replacement.json()["status"], "PENDING_APPROVAL")
        self.assertEqual(replacement.json()["supersedes"], decision_id)

        approved_replacement = restarted.post(
            f"/api/v1/decisions/{replacement_id}/approve"
        )
        self.assertEqual(approved_replacement.status_code, 200)
        self.assertEqual(approved_replacement.json()["status"], "APPROVED")

        original = restarted.get(f"/api/v1/decisions/{decision_id}").json()
        self.assertEqual(original["status"], "SUPERSEDED")

        audit = restarted.get(
            f"/api/v1/decisions/{decision_id}/audit"
        ).json()
        self.assertEqual(
            [event["event_type"] for event in audit],
            [
                "DECISION_CREATED",
                "DECISION_APPROVED",
                "PROJECTION_NOT_CONFIGURED",
                "DECISION_INVALIDATED",
                "DECISION_REVALIDATION_STARTED",
                "DECISION_SUPERSEDED",
            ],
        )

        replacement_audit = restarted.get(
            f"/api/v1/decisions/{replacement_id}/audit"
        ).json()
        self.assertEqual(
            [event["event_type"] for event in replacement_audit],
            [
                "DECISION_CREATED",
                "DECISION_APPROVED",
                "PROJECTION_NOT_CONFIGURED",
            ],
        )

    def test_approval_projects_when_datahub_is_configured(self) -> None:
        os.environ["DATAHUB_GMS_URL"] = "http://datahub.test"
        client = TestClient(
            create_app(db_path=self.db_path, adapter_factory=SuccessfulAdapter)
        )
        decision_id = client.post("/api/v1/decisions/run").json()["id"]
        approved = client.post(f"/api/v1/decisions/{decision_id}/approve")

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["projection_status"], "SYNCED")
        self.assertEqual(
            approved.json()["datahub_urn"],
            f"urn:li:document:decisiongraph-{decision_id}",
        )

    def test_failed_projection_can_be_retried(self) -> None:
        FlakyAdapter.attempts = 0
        os.environ["DATAHUB_GMS_URL"] = "http://datahub.test"
        client = TestClient(
            create_app(db_path=self.db_path, adapter_factory=FlakyAdapter)
        )
        decision_id = client.post("/api/v1/decisions/run").json()["id"]

        approved = client.post(f"/api/v1/decisions/{decision_id}/approve")
        self.assertEqual(
            approved.json()["projection_status"], "RETRY_REQUIRED"
        )
        self.assertIn("temporary outage", approved.json()["projection_error"])

        retried = client.post(f"/api/v1/decisions/{decision_id}/sync")
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["projection_status"], "SYNCED")
        self.assertIsNone(retried.json()["projection_error"])

    def test_unexpected_projection_timeout_becomes_retry_required(self) -> None:
        os.environ["DATAHUB_GMS_URL"] = "http://datahub.test"
        client = TestClient(
            create_app(db_path=self.db_path, adapter_factory=TimeoutAdapter)
        )
        decision_id = client.post("/api/v1/decisions/run").json()["id"]

        approved = client.post(f"/api/v1/decisions/{decision_id}/approve")

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(
            approved.json()["projection_status"], "RETRY_REQUIRED"
        )
        self.assertIn("socket timed out", approved.json()["projection_error"])

    def test_false_datahub_health_is_unavailable(self) -> None:
        os.environ["DATAHUB_GMS_URL"] = "http://datahub.test"
        client = TestClient(
            create_app(
                db_path=self.db_path,
                adapter_factory=FalseHealthAdapter,
            )
        )
        response = client.get("/api/v1/datahub/health")
        self.assertEqual(response.status_code, 503)

    def test_mcp_context_is_persisted_and_refetched_for_revalidation(self) -> None:
        MCPContextProvider.calls = 0
        client = TestClient(
            create_app(
                db_path=self.db_path,
                context_provider_factory=MCPContextProvider,
            )
        )
        created = client.post("/api/v1/decisions/run").json()
        self.assertEqual(created["context"]["source"], "datahub_mcp_server")
        self.assertEqual(
            created["context"]["tools"],
            ["get_entities", "list_schema_fields"],
        )
        self.assertEqual(created["context"]["snapshot"]["retrieval"], 1)

        decision_id = created["id"]
        client.post(f"/api/v1/decisions/{decision_id}/approve")
        asset_urn = created["dependencies"][0]["asset_urn"]
        client.post(
            "/api/v1/events/invalidation",
            json={"asset_urn": asset_urn},
        )
        replacement = client.post(
            f"/api/v1/decisions/{decision_id}/revalidate"
        ).json()

        self.assertEqual(replacement["context"]["snapshot"]["retrieval"], 2)
        self.assertIn("freshly retrieved", replacement["summary"])

    def test_configured_context_failure_does_not_fall_back_to_fixture(self) -> None:
        client = TestClient(
            create_app(
                db_path=self.db_path,
                context_provider_factory=FailingContextProvider,
            )
        )
        response = client.post("/api/v1/decisions/run")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(client.get("/api/v1/decisions").json(), [])

    def test_revalidate_conflicts_until_decision_is_invalidated(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        decision_id = client.post("/api/v1/decisions/run").json()["id"]
        self.assertEqual(
            client.post(f"/api/v1/decisions/{decision_id}/revalidate").status_code,
            409,
        )

    def test_unmatched_invalidation_event_is_still_durable(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        response = client.post(
            "/api/v1/events/invalidation",
            json={
                "asset_urn": "urn:li:dataset:(urn:li:dataPlatform:demo,missing,PROD)",
                "event_type": "DATASET_STALE",
                "severity": "critical",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

        events = client.get("/api/v1/events/invalidation").json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "critical")
        self.assertEqual(events[0]["impacted_decision_ids"], [])

    def test_dashboard_shell_is_served(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("DecisionGraph Console", response.text)
        self.assertIn("Verified DataHub Integration Snapshot", response.text)

    def test_recorded_live_integration_snapshot_is_served(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        response = client.get("/assets/integration-proof.json")
        self.assertEqual(response.status_code, 200)
        proof = response.json()
        self.assertEqual(proof["context_source"], "datahub_mcp_server")
        self.assertEqual(
            proof["mcp_tools"], ["get_entities", "list_schema_fields"]
        )
        self.assertEqual(proof["projection_status"], "SYNCED")
        self.assertTrue(proof["read_back_verified"])
        self.assertEqual(len(proof["context_facts"]), 3)
        self.assertEqual(len(proof["related_assets"]), 2)


if __name__ == "__main__":
    unittest.main()
