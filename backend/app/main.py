from collections.abc import Callable
import os
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .comparison import compare_decisions
from .datahub_adapter import DataHubAdapter, DataHubConfig, DataHubUnavailable
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
    InvalidationEvent,
    InvalidationRecord,
    ProjectionStatus,
)
from .store import DecisionStore

AdapterFactory = Callable[[DataHubConfig], DataHubAdapter]
ContextProviderFactory = Callable[[], ContextProvider]


def create_app(
    *,
    db_path: str | Path | None = None,
    adapter_factory: AdapterFactory = DataHubAdapter,
    context_provider_factory: ContextProviderFactory = (
        context_provider_from_environment
    ),
) -> FastAPI:
    api = FastAPI(title="DecisionGraph API", version="0.2.0")
    static_dir = Path(__file__).parent / "static"
    dashboard_html = static_dir / "index.html"
    ledger_path = db_path or os.getenv("DECISIONGRAPH_DB_PATH", "decisiongraph.db")
    store = DecisionStore(ledger_path)
    api.state.store = store
    api.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    def project(decision: Decision) -> Decision:
        config = DataHubConfig.from_environment()
        if not config:
            return store.set_projection(
                decision.id, ProjectionStatus.NOT_CONFIGURED, error=None
            )
        store.set_projection(decision.id, ProjectionStatus.PENDING, error=None)
        evidence = "\n".join(f"- {fact}" for fact in decision.evidence)
        document_text = f"# {decision.title}\n\n{decision.summary}\n\n## Evidence\n{evidence}"
        try:
            urn = adapter_factory(config).create_decision_document(
                decision_id=str(decision.id),
                title=decision.title,
                summary=document_text,
                related_assets=[edge.asset_urn for edge in decision.dependencies],
            )
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
        return store.create(
            Decision(
                title="Reorder Northeast products",
                summary=(
                    "Reorder three high-demand products using context retrieved "
                    "through the official DataHub MCP Server."
                    if context.source == "datahub_mcp_server"
                    else (
                        "Reorder three high-demand products using the seeded "
                        "retail inventory fixture."
                    )
                ),
                evidence=context.facts,
                dependencies=DECISION_DEPENDENCIES,
                context=context,
            )
        )

    @api.post("/api/v1/decisions/{decision_id}/approve")
    def approve_decision(decision_id: UUID) -> Decision:
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
        return project(approved)

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
                        f"Supersedes decision {decision.id} after a fresh "
                        "context retrieval."
                    ),
                ],
                dependencies=DECISION_DEPENDENCIES,
                context=context,
                supersedes=decision.id,
            ),
        )
        if replacement is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return replacement

    @api.post("/api/v1/decisions/{decision_id}/sync")
    def sync_decision(decision_id: UUID) -> Decision:
        decision = store.get(decision_id)
        if not decision:
            raise HTTPException(status_code=404, detail="Decision not found")
        if decision.status is not DecisionStatus.APPROVED:
            raise HTTPException(
                status_code=409, detail="Only approved decisions can be projected"
            )
        return project(decision)

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
