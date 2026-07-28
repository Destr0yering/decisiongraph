from collections.abc import Callable
import asyncio
import inspect
import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .agent_registry import (
    AgentRegistryUnavailable,
    DecisionGraphAgentRegistrar,
    agent_registry_sdk_status,
)
from .analytics_agent import (
    AnalyticsAgentClient,
    AnalyticsAgentConfig,
    AnalyticsUnavailable,
    ReorderAnalysisProvider,
    analysis_provider_from_environment,
)
from .comparison import compare_decisions
from .datahub_adapter import (
    DataHubAdapter,
    DataHubConfig,
    DataHubUnavailable,
    datahub_adapter_from_config,
)
from .mcp_context import (
    ContextProvider,
    ContextUnavailable,
    DECISION_DEPENDENCIES,
    context_provider_from_environment,
)
from .models import (
    Decision,
    DecisionComparison,
    DecisionStatus,
    AgentRegistration,
    InvalidationEvent,
    InvalidationRecord,
    ProjectionStatus,
)
from .store import DecisionStore

AdapterFactory = Callable[[DataHubConfig], DataHubAdapter]
ContextProviderFactory = Callable[[], ContextProvider]
AnalysisProviderFactory = Callable[[], ReorderAnalysisProvider]
RegistrarFactory = Callable[[DataHubConfig], DecisionGraphAgentRegistrar]


def create_app(
    *,
    db_path: str | Path | None = None,
    adapter_factory: AdapterFactory = datahub_adapter_from_config,
    context_provider_factory: ContextProviderFactory = (
        context_provider_from_environment
    ),
    analysis_provider_factory: AnalysisProviderFactory = (
        analysis_provider_from_environment
    ),
    registrar_factory: RegistrarFactory = DecisionGraphAgentRegistrar,
) -> FastAPI:
    api = FastAPI(title="DecisionGraph API", version="0.3.0")
    static_dir = Path(__file__).parent / "static"
    dashboard_html = static_dir / "index.html"
    ledger_path = db_path or os.getenv("DECISIONGRAPH_DB_PATH", "decisiongraph.db")
    store = DecisionStore(ledger_path)
    api.state.store = store
    api.state.agent_registration = None
    api.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    async def project(decision: Decision) -> Decision:
        config = DataHubConfig.from_environment()
        if not config:
            return store.set_projection(
                decision.id, ProjectionStatus.NOT_CONFIGURED, error=None
            )
        store.set_projection(decision.id, ProjectionStatus.PENDING, error=None)
        evidence = "\n".join(f"- {fact}" for fact in decision.evidence)
        dependencies = "\n".join(
            f"- `{edge.asset_urn}`" for edge in decision.dependencies
        )
        analysis = decision.analysis
        analysis_text = ""
        if analysis:
            rows = "\n".join(
                f"- {row}" for row in analysis.rows[:20]
            )
            analysis_text = (
                "\n\n## Analytics Agent\n"
                f"Source: `{analysis.source}`\n\n"
                f"{analysis.answer}\n\n"
                "### SQL\n"
                f"```sql\n{analysis.sql or '-- not recorded'}\n```\n\n"
                f"### Result rows\n{rows or '- No rows returned'}"
            )
        revision_text = (
            f"\n\n## Supersedes\n`{decision.supersedes}`"
            if decision.supersedes
            else ""
        )
        document_text = (
            f"# {decision.title}\n\n{decision.summary}\n\n"
            f"## Evidence\n{evidence}\n\n"
            f"## Governed dependencies\n{dependencies}"
            f"{analysis_text}{revision_text}"
        )
        try:
            result = adapter_factory(config).create_decision_document(
                decision_id=str(decision.id),
                title=decision.title,
                summary=document_text,
                related_assets=[edge.asset_urn for edge in decision.dependencies],
                existing_urn=decision.datahub_urn,
            )
            urn = await result if inspect.isawaitable(result) else result
        except Exception as error:
            message = str(error).strip() or type(error).__name__
            return store.set_projection(
                decision.id,
                ProjectionStatus.RETRY_REQUIRED,
                error=message[:240],
            )
        return store.set_projection(
            decision.id,
            ProjectionStatus.SYNCED,
            datahub_urn=urn,
            error=None,
        )

    @api.get("/health")
    def health() -> dict[str, str]:
        mcp_enabled = os.getenv("DATAHUB_MCP_ENABLED", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return {
            "status": "ok",
            "mode": "datahub-mcp" if mcp_enabled else "deterministic-demo",
            "analytics": (
                "datahub-analytics-agent"
                if os.getenv("ANALYTICS_AGENT_ENABLED", "").lower()
                in {"1", "true", "yes", "on"}
                else "deterministic-fixture"
            ),
        }

    @api.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return dashboard_html.read_text(encoding="utf-8")

    @api.get("/api/v1/datahub/health")
    def datahub_health() -> dict[str, str]:
        config = DataHubConfig.from_environment()
        if not config:
            return {"status": "not_configured"}
        try:
            connected = adapter_factory(config).healthcheck()
        except DataHubUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if not connected:
            raise HTTPException(
                status_code=503, detail="DataHub health check failed"
            )
        return {"status": "connected"}

    @api.get("/api/v1/analytics-agent/health")
    async def analytics_agent_health() -> dict[str, str]:
        try:
            config = AnalyticsAgentConfig.from_environment()
        except AnalyticsUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if not config:
            return {"status": "not_configured"}
        if not await AnalyticsAgentClient(config).healthcheck():
            raise HTTPException(
                status_code=503,
                detail="DataHub Analytics Agent health check failed",
            )
        return {"status": "connected", "engine": config.engine_name}

    @api.get("/api/v1/datahub/agent-registry")
    def agent_registry_status() -> dict[str, object]:
        registration = api.state.agent_registration
        if registration is None:
            available, detail = agent_registry_sdk_status()
            return {
                "status": "not_registered" if available else "sdk_unavailable",
                "sdk_available": available,
                "detail": detail,
            }
        return {
            "status": "registered",
            "sdk_available": True,
            **registration.model_dump(mode="json"),
        }

    @api.post(
        "/api/v1/datahub/agent-registry",
        response_model=AgentRegistration,
    )
    async def register_agent() -> AgentRegistration:
        config = DataHubConfig.from_environment()
        if not config:
            raise HTTPException(
                status_code=503,
                detail="DATAHUB_GMS_URL is required for Agent Registry",
            )
        try:
            registration = await asyncio.to_thread(
                registrar_factory(config).register,
                [edge.asset_urn for edge in DECISION_DEPENDENCIES],
            )
        except AgentRegistryUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        api.state.agent_registration = registration
        return registration

    @api.get("/api/v1/decisions")
    def list_decisions() -> list[Decision]:
        return store.list()

    @api.get("/api/v1/decisions/{decision_id}")
    def get_decision(decision_id: UUID) -> Decision:
        decision = store.get(decision_id)
        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")
        return decision

    @api.get("/api/v1/decisions/{decision_id}/audit")
    def get_audit(decision_id: UUID) -> list[dict[str, object]]:
        if not store.get(decision_id):
            raise HTTPException(status_code=404, detail="Decision not found")
        return store.audit_events(decision_id)

    @api.get(
        "/api/v1/decisions/{decision_id}/comparison",
        response_model=DecisionComparison,
    )
    def get_comparison(decision_id: UUID) -> DecisionComparison:
        selected = store.get(decision_id)
        if not selected:
            raise HTTPException(status_code=404, detail="Decision not found")
        if selected.supersedes:
            prior = store.get(selected.supersedes)
            current = selected
        else:
            prior = selected
            current = store.replacement_for(selected.id)
        if not prior or not current:
            raise HTTPException(
                status_code=404,
                detail="No prior and updated revision pair exists",
            )
        return compare_decisions(prior, current)

    @api.post("/api/v1/decisions/run", status_code=201)
    async def run_reorder_decision() -> Decision:
        """Create a decision grounded in fixture or official DataHub MCP context."""
        try:
            context = await context_provider_factory().fetch_reorder_context()
        except ContextUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        try:
            analysis = await analysis_provider_factory().analyze_reorder(context)
        except AnalyticsUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        result_count = len(analysis.rows)
        quality = analysis.context_quality or {}
        quality_label = quality.get("label")
        analysis_evidence = [
            (
                f"DataHub Analytics Agent executed governed SQL and returned "
                f"{result_count} reorder candidate rows."
                if analysis.source == "datahub_analytics_agent"
                else (
                    f"Deterministic Analytics Agent fixture returned "
                    f"{result_count} reorder candidate rows."
                )
            )
        ]
        if quality_label:
            analysis_evidence.append(
                f"Analytics context quality was reported as {quality_label}."
            )
        return store.create(
            Decision(
                title="Reorder Northeast products",
                summary=(
                    f"Review {result_count} Northeast reorder candidates "
                    f"computed by {'DataHub Analytics Agent' if analysis.source == 'datahub_analytics_agent' else 'the deterministic analytics fixture'} "
                    "against governed DataHub evidence before approval."
                ),
                evidence=[*context.facts, *analysis_evidence],
                dependencies=DECISION_DEPENDENCIES,
                context=context,
                analysis=analysis,
            )
        )

    @api.post("/api/v1/decisions/{decision_id}/approve")
    async def approve_decision(decision_id: UUID) -> Decision:
        before = store.get(decision_id)
        if not before:
            raise HTTPException(status_code=404, detail="Decision not found")
        if before.status is not DecisionStatus.PENDING_APPROVAL:
            raise HTTPException(
                status_code=409, detail="Only pending decisions can be approved"
            )
        approved = store.approve(decision_id)
        if approved is None:
            raise HTTPException(status_code=409, detail="Decision approval conflict")
        return await project(approved)

    @api.post("/api/v1/decisions/{decision_id}/revalidate")
    async def revalidate_decision(decision_id: UUID) -> Decision:
        decision = store.get(decision_id)
        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")
        if decision.status is not DecisionStatus.REVALIDATION_REQUIRED:
            raise HTTPException(
                status_code=409,
                detail="Only invalidated decisions can create a revalidation revision",
            )
        try:
            context = await context_provider_factory().fetch_reorder_context()
        except ContextUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        try:
            analysis = await analysis_provider_factory().analyze_reorder(context)
        except AnalyticsUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        replacement = store.revalidate(
            decision_id,
            Decision(
                title=f"{decision.title} (Revalidated)",
                summary=(
                    f"{decision.summary} Revalidated with freshly retrieved "
                    "DataHub context after an upstream dependency change."
                ),
                evidence=[
                    *context.facts,
                    (
                        "DataHub Analytics Agent re-ran the governed query and "
                        f"returned {len(analysis.rows)} candidate rows."
                        if analysis.source == "datahub_analytics_agent"
                        else (
                            "Deterministic Analytics Agent fixture was rerun "
                            f"and returned {len(analysis.rows)} candidate rows."
                        )
                    ),
                    (
                        f"Supersedes decision {decision.id} after a fresh "
                        "context retrieval."
                    ),
                ],
                dependencies=DECISION_DEPENDENCIES,
                context=context,
                analysis=analysis,
                supersedes=decision.id,
            ),
        )
        if replacement is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return replacement

    @api.post("/api/v1/decisions/{decision_id}/sync")
    async def sync_decision(decision_id: UUID) -> Decision:
        decision = store.get(decision_id)
        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")
        if decision.status is not DecisionStatus.APPROVED:
            raise HTTPException(
                status_code=409, detail="Only approved decisions can be projected"
            )
        return await project(decision)

    @api.post("/api/v1/events/invalidation")
    def invalidate(event: InvalidationEvent) -> list[Decision]:
        return store.invalidate(
            event.asset_urn,
            event.event_type,
            event.severity,
        )

    @api.get("/api/v1/events/invalidation")
    def list_invalidation_events() -> list[InvalidationRecord]:
        return store.invalidation_events()

    return api


app = create_app()
