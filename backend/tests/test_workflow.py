import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.datahub_adapter import (
    DataHubUnavailable,
    DataHubVerificationUnavailable,
)
from app.analytics_agent import (
    AnalyticsAgentClient,
    AnalyticsAgentConfig,
    AnalyticsUnavailable,
    REORDER_SQL,
)
from app.main import create_app
from app.mcp_context import ContextUnavailable
from app.mcp_runtime import datahub_mcp_environment
from app.models import (
    AgentRegistration,
    DecisionContext,
    ReorderAnalysis,
)


class SuccessfulAdapter:
    def __init__(self, _config):
        pass

    def healthcheck(self) -> bool:
        return True

    def create_decision_document(
        self,
        *,
        decision_id: str,
        title: str,
        summary: str,
        related_assets: list[str],
        existing_urn: str | None = None,
    ) -> str:
        assert title
        assert "## Evidence" in summary
        assert len(related_assets) == 2
        return f"urn:li:document:decisiongraph-{decision_id}"


class FlakyAdapter(SuccessfulAdapter):
    attempts = 0

    def create_decision_document(
        self,
        *,
        decision_id: str,
        title: str,
        summary: str,
        related_assets: list[str],
        existing_urn: str | None = None,
    ) -> str:
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise DataHubUnavailable("temporary outage")
        return super().create_decision_document(
            decision_id=decision_id,
            title=title,
            summary=summary,
            related_assets=related_assets,
            existing_urn=existing_urn,
        )


class TimeoutAdapter(SuccessfulAdapter):
    def create_decision_document(self, **_kwargs) -> str:
        raise TimeoutError("socket timed out")


class VerificationFlakyAdapter(SuccessfulAdapter):
    attempts = 0
    urn: str | None = None

    def create_decision_document(self, *, decision_id: str, existing_urn=None, **kwargs):
        type(self).attempts += 1
        expected_urn = f"urn:li:document:decisiongraph-{decision_id}"
        if type(self).attempts == 1:
            type(self).urn = expected_urn
            raise DataHubVerificationUnavailable(
                "read-back temporarily unavailable", expected_urn
            )
        assert existing_urn == type(self).urn
        return expected_urn


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


class AnalyticsProvider:
    calls = 0

    async def analyze_reorder(
        self, _context: DecisionContext
    ) -> ReorderAnalysis:
        type(self).calls += 1
        count = type(self).calls + 2
        rows = [
            {
                "sku": f"NE-{index}",
                "recommended_reorder_quantity": index + 10,
            }
            for index in range(count)
        ]
        return ReorderAnalysis(
            source="datahub_analytics_agent",
            question="Which Northeast products need reorder?",
            conversation_id=f"conversation-{type(self).calls}",
            engine_name="fiction-retail",
            answer=f"{count} governed products require reorder.",
            sql="SELECT * FROM governed_reorder_candidates",
            columns=["sku", "recommended_reorder_quantity"],
            rows=rows,
            chart={"mark": "bar"},
            context_quality={"score": 5, "label": "Excellent"},
            tool_calls=["search", "get_entities", "execute_sql"],
        )


class FailingAnalyticsProvider:
    async def analyze_reorder(
        self, _context: DecisionContext
    ) -> ReorderAnalysis:
        raise AnalyticsUnavailable("Analytics Agent unavailable")


class SuccessfulRegistrar:
    def __init__(self, _config):
        pass

    def register(
        self, consumed_dataset_urns: list[str]
    ) -> AgentRegistration:
        return AgentRegistration(
            agent_urn="urn:li:aiAgent:decisiongraph",
            skill_urn=(
                "urn:li:agentSkill:evidence-bound-decision-governance"
            ),
            tool_urns=[
                "urn:li:api:decisiongraph.propose-decision",
                "urn:li:api:decisiongraph.approve-decision",
            ],
            consumed_dataset_urns=consumed_dataset_urns,
        )


class DecisionWorkflowTests(unittest.TestCase):
    def test_mcp_subprocess_disables_telemetry_by_default(self) -> None:
        environment = datahub_mcp_environment(
            gms_url="http://datahub.test",
            gms_token=None,
            mutations_enabled=False,
        )

        self.assertEqual(
            environment["DATAHUB_TELEMETRY_ENABLED"], "false"
        )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "decisiongraph.db"
        self.previous_url = os.environ.pop("DATAHUB_GMS_URL", None)
        self.previous_mcp_enabled = os.environ.pop(
            "DATAHUB_MCP_ENABLED", None
        )
        self.analytics_environment = {
            key: os.environ.pop(key, None)
            for key in (
                "ANALYTICS_AGENT_ENABLED",
                "ANALYTICS_AGENT_URL",
                "ANALYTICS_AGENT_ENGINE",
            )
        }

    def tearDown(self) -> None:
        if self.previous_url is not None:
            os.environ["DATAHUB_GMS_URL"] = self.previous_url
        else:
            os.environ.pop("DATAHUB_GMS_URL", None)
        if self.previous_mcp_enabled is not None:
            os.environ["DATAHUB_MCP_ENABLED"] = self.previous_mcp_enabled
        else:
            os.environ.pop("DATAHUB_MCP_ENABLED", None)
        for key, value in self.analytics_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
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

        VerificationFlakyAdapter.attempts = 0
        VerificationFlakyAdapter.urn = None
        verification_client = TestClient(
            create_app(
                db_path=Path(self.temp_dir.name) / "verification.db",
                adapter_factory=VerificationFlakyAdapter,
            )
        )
        verification_id = verification_client.post(
            "/api/v1/decisions/run"
        ).json()["id"]
        first = verification_client.post(
            f"/api/v1/decisions/{verification_id}/approve"
        ).json()
        self.assertEqual(first["projection_status"], "RETRY_REQUIRED")
        self.assertEqual(first["datahub_urn"], VerificationFlakyAdapter.urn)
        second = verification_client.post(
            f"/api/v1/decisions/{verification_id}/sync"
        )
        self.assertEqual(second.json()["projection_status"], "SYNCED")
        self.assertEqual(VerificationFlakyAdapter.attempts, 2)
        idempotent = verification_client.post(
            f"/api/v1/decisions/{verification_id}/sync"
        )
        self.assertEqual(idempotent.status_code, 200)
        self.assertEqual(VerificationFlakyAdapter.attempts, 2)

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

        os.environ["ANALYTICS_AGENT_ENABLED"] = "true"
        os.environ["ANALYTICS_AGENT_URL"] = "http://analytics.test"
        os.environ["ANALYTICS_AGENT_ENGINE"] = "warehouse"
        with patch(
            "app.main.AnalyticsAgentClient.healthcheck",
            new=AsyncMock(side_effect=AnalyticsUnavailable("agent offline")),
        ):
            analytics_response = client.get("/api/v1/analytics-agent/health")
        self.assertEqual(analytics_response.status_code, 503)
        self.assertIn("agent offline", analytics_response.json()["detail"])

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

    def test_revision_comparison_exposes_changes_and_routine_impacts(self) -> None:
        MCPContextProvider.calls = 0
        client = TestClient(
            create_app(
                db_path=self.db_path,
                context_provider_factory=MCPContextProvider,
            )
        )
        prior = client.post("/api/v1/decisions/run").json()
        client.post(f"/api/v1/decisions/{prior['id']}/approve")
        client.post(
            "/api/v1/events/invalidation",
            json={"asset_urn": prior["dependencies"][0]["asset_urn"]},
        )
        current = client.post(
            f"/api/v1/decisions/{prior['id']}/revalidate"
        ).json()

        comparison = client.get(
            f"/api/v1/decisions/{current['id']}/comparison"
        )
        self.assertEqual(comparison.status_code, 200)
        payload = comparison.json()
        self.assertEqual(payload["prior"]["id"], prior["id"])
        self.assertEqual(payload["current"]["id"], current["id"])
        changed_paths = {change["path"] for change in payload["changes"]}
        self.assertIn("context.facts", changed_paths)
        self.assertIn("context.snapshot.retrieval", changed_paths)
        routines = {
            impact["routine"] for impact in payload["routine_impacts"]
        }
        self.assertEqual(
            routines,
            {
                "retrieve_context",
                "build_recommendation",
                "request_human_approval",
                "project_datahub_document",
            },
        )

        comparison_from_prior = client.get(
            f"/api/v1/decisions/{prior['id']}/comparison"
        ).json()
        self.assertEqual(comparison_from_prior["current"]["id"], current["id"])

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

    def test_analytics_agent_output_is_persisted_and_recomputed(self) -> None:
        AnalyticsProvider.calls = 0
        client = TestClient(
            create_app(
                db_path=self.db_path,
                context_provider_factory=MCPContextProvider,
                analysis_provider_factory=AnalyticsProvider,
            )
        )
        created = client.post("/api/v1/decisions/run").json()
        self.assertEqual(
            created["analysis"]["source"], "datahub_analytics_agent"
        )
        self.assertEqual(
            created["analysis"]["conversation_id"], "conversation-1"
        )
        self.assertEqual(len(created["analysis"]["rows"]), 3)
        self.assertIn("SELECT", created["analysis"]["sql"])

        client.post(f"/api/v1/decisions/{created['id']}/approve")
        client.post(
            "/api/v1/events/invalidation",
            json={"asset_urn": created["dependencies"][0]["asset_urn"]},
        )
        replacement = client.post(
            f"/api/v1/decisions/{created['id']}/revalidate"
        ).json()
        self.assertEqual(
            replacement["analysis"]["conversation_id"], "conversation-2"
        )
        self.assertEqual(len(replacement["analysis"]["rows"]), 4)

        comparison = client.get(
            f"/api/v1/decisions/{replacement['id']}/comparison"
        ).json()
        paths = {change["path"] for change in comparison["changes"]}
        self.assertIn("analysis.rows", paths)
        routines = {
            impact["routine"] for impact in comparison["routine_impacts"]
        }
        self.assertIn("run_analytics_agent", routines)

    def test_configured_analytics_failure_does_not_create_decision(self) -> None:
        client = TestClient(
            create_app(
                db_path=self.db_path,
                analysis_provider_factory=FailingAnalyticsProvider,
            )
        )
        response = client.post("/api/v1/decisions/run")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(client.get("/api/v1/decisions").json(), [])

    def test_agent_registry_registration_exposes_skill_tools_and_lineage(
        self,
    ) -> None:
        os.environ["DATAHUB_GMS_URL"] = "http://datahub.test"
        client = TestClient(
            create_app(
                db_path=self.db_path,
                registrar_factory=SuccessfulRegistrar,
            )
        )
        registration = client.post("/api/v1/datahub/agent-registry")
        self.assertEqual(registration.status_code, 200)
        payload = registration.json()
        self.assertEqual(
            payload["agent_urn"], "urn:li:aiAgent:decisiongraph"
        )
        self.assertEqual(len(payload["consumed_dataset_urns"]), 2)
        self.assertEqual(len(payload["tool_urns"]), 2)

        status = client.get("/api/v1/datahub/agent-registry").json()
        self.assertEqual(status["status"], "registered")
        self.assertEqual(status["skill_urn"], payload["skill_urn"])

    def test_analytics_agent_sse_contract_is_preserved(self) -> None:
        class StubAnalyticsAgentClient(AnalyticsAgentClient):
            def _request(
                self,
                method: str,
                path: str,
                body: dict[str, object] | None = None,
                *,
                accept: str = "application/json",
            ) -> tuple[str, str]:
                if path == "/api/conversations":
                    self.assert_request(method, body)
                    return '{"id":"conversation-42"}', "application/json"
                if path.endswith("/messages"):
                    self_test.assertEqual(accept, "text/event-stream")
                    return (
                        'data: {"event":"TOOL_CALL","payload":{"tool_name":"run_sql"}}\n'
                        'data: {"event":"SQL","payload":{"sql":'
                        + json.dumps(REORDER_SQL)
                        + ',"columns":["product_id","on_hand_units","forecast_units","recommended_reorder_quantity"],"rows":[{"product_id":"NE-104","on_hand_units":75,"forecast_units":100,"recommended_reorder_quantity":25}]}}\n'
                        'data: {"event":"CHART","payload":{"vega_lite_spec":{"mark":"bar"}}}\n'
                        'data: {"event":"COMPLETE","payload":{"text":"Reorder 25 units."}}\n',
                        "text/event-stream",
                    )
                if path.endswith("/quality"):
                    return '{"score":5,"label":"Excellent"}', "application/json"
                raise AssertionError(path)

            def assert_request(
                self,
                method: str,
                body: dict[str, object] | None,
            ) -> None:
                self_test.assertEqual(method, "POST")
                self_test.assertEqual(body["engine_name"], "warehouse")

        self_test = self
        client = StubAnalyticsAgentClient(
            AnalyticsAgentConfig(
                base_url="http://analytics-agent.test",
                engine_name="warehouse",
            )
        )
        analysis = asyncio.run(
            client.analyze_reorder(
                DecisionContext(
                    source="datahub_mcp_server",
                    facts=["Two governed datasets retrieved."],
                )
            )
        )
        self.assertEqual(analysis.source, "datahub_analytics_agent")
        self.assertEqual(analysis.conversation_id, "conversation-42")
        self.assertEqual(analysis.sql, REORDER_SQL)
        self.assertEqual(analysis.rows[0]["recommended_reorder_quantity"], 25)
        self.assertEqual(
            analysis.answer,
            (
                "Analytics Agent executed the governed SQL query and returned "
                "1 Northeast reorder candidates: NE-104."
            ),
        )
        self.assertEqual(
            analysis.chart,
            {
                "mark": "bar",
                "data": {
                    "values": [
                        {
                            "product_id": "NE-104",
                            "on_hand_units": 75,
                            "forecast_units": 100,
                            "recommended_reorder_quantity": 25,
                        }
                    ]
                },
            },
        )
        self.assertEqual(analysis.context_quality["score"], 5)
        self.assertEqual(analysis.tool_calls, ["run_sql"])

        class WrongSqlClient(StubAnalyticsAgentClient):
            def _request(self, method, path, body=None, *, accept="application/json"):
                raw, content_type = super()._request(
                    method, path, body, accept=accept
                )
                if path.endswith("/messages"):
                    raw = raw.replace(REORDER_SQL, "SELECT 1")
                return raw, content_type

        with self.assertRaisesRegex(AnalyticsUnavailable, "governed reorder SQL"):
            asyncio.run(
                WrongSqlClient(client.config).analyze_reorder(
                    DecisionContext(
                        source="datahub_mcp_server",
                        facts=["Two governed datasets retrieved."],
                    )
                )
            )

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
        self.assertIn("Your data changed.", response.text)
        self.assertIn("Verified DataHub Integration Snapshot", response.text)
        self.assertIn("Prior Data → Updated Data → Routine Impact", response.text)
        self.assertIn("Replay Live JSON", response.text)
        self.assertIn("Agent Registry Compatibility", response.text)

    def test_recorded_live_integration_snapshot_is_served(self) -> None:
        client = TestClient(create_app(db_path=self.db_path))
        response = client.get("/assets/live-revalidation-proof.json")
        self.assertEqual(response.status_code, 200)
        proof = response.json()
        self.assertEqual(proof["context_source"], "datahub_mcp_server")
        self.assertEqual(
            proof["mcp_tools"],
            [
                "get_entities",
                "list_schema_fields",
                "get_lineage",
                "save_document",
            ],
        )
        self.assertEqual(proof["projection_status"], "SYNCED")
        self.assertTrue(proof["read_back_verified"])
        self.assertEqual(proof["verification_type"], "recorded_live_integration_and_revalidation_run")
        self.assertEqual(proof["datahub_version"], "1.6.0")
        self.assertTrue(proof["verified_at"].endswith("Z"))
        self.assertTrue(proof["disclosure"])
        self.assertEqual(len(proof["context_facts"]), 3)
        self.assertEqual(len(proof["datasets"]), 2)
        self.assertTrue(
            all(
                dataset["urn"] and dataset["schema_field_count"] > 0
                for dataset in proof["datasets"]
            )
        )
        self.assertEqual(len(proof["related_assets"]), 2)
        self.assertEqual(proof["analytics"]["updated_row_count"], 4)
        self.assertEqual(proof["analytics"]["source"], "datahub_analytics_agent")
        self.assertTrue(proof["analytics"]["conversation_id"])
        self.assertEqual(proof["analytics"]["tool_calls"], ["execute_sql"])
        self.assertEqual(
            set(proof["analytics"]["new_row"]),
            {
                "product_id",
                "on_hand_units",
                "forecast_units",
                "recommended_reorder_quantity",
            },
        )
        self.assertTrue(proof["analytics"]["sql_rows_and_chart_match"])
        self.assertEqual(proof["lifecycle"]["prior_status"], "SUPERSEDED")
        self.assertEqual(proof["lifecycle"]["replacement_status"], "APPROVED")
        self.assertGreater(proof["lifecycle"]["highlighted_change_count"], 0)
        self.assertEqual(len(proof["lifecycle"]["affected_routines"]), 5)
        self.assertTrue(proof["datahub_document_urn"].startswith("urn:li:document:"))
        self.assertEqual(proof["automated_tests_passed"], 17)


if __name__ == "__main__":
    unittest.main()
