# DecisionGraph

DecisionGraph gives AI-assisted decisions traceable evidence, approval history,
and recall when the DataHub context they depend on changes. It reads governed
dataset context through the official open-source DataHub MCP Server and writes
approved decision records back as native DataHub Documents.

**Hackathon category:** Agents That Do Real Work

## MVP scope

1. Retrieve rich entity context, schemas, and downstream lineage with DataHub MCP.
2. Ask DataHub's open-source Analytics Agent to compute the reorder recommendation
   and preserve its SQL, rows, chart, quality score, and conversation provenance.
3. Create an evidence-grounded decision with explicit DataHub URN dependencies.
4. Require approval before the decision can be written to DataHub.
5. Persist the approved record with MCP `save_document` and verify it by read-back.
6. Detect changed evidence, highlight its downstream routine impact, and create a
   replacement revision without destroying the prior record.

DataHub remains the source of truth for metadata and lineage. DecisionGraph keeps workflow state, audit history, and retry-safe projections locally, then mirrors supported records and associations back to DataHub.

## Initial API

The FastAPI service is in `backend/`. It does not require an LLM: the agent
workflow keeps its context and analytics sources explicit. With
`DATAHUB_MCP_ENABLED=true`, decision creation invokes the official MCP tools
`get_entities`, `list_schema_fields`, and `get_lineage`. With
`ANALYTICS_AGENT_ENABLED=true`, the calculation is delegated to
[`datahub-project/analytics-agent`](https://github.com/datahub-project/analytics-agent).
When `DATAHUB_MCP_MUTATIONS_ENABLED=true`, approval uses MCP `save_document`
and reads the new Document back; otherwise the existing GraphQL projection
adapter remains available. Workflow state and audit history are durable in SQLite.

```text
POST /api/v1/decisions/run
POST /api/v1/decisions/{decision_id}/approve
POST /api/v1/decisions/{decision_id}/revalidate
POST /api/v1/decisions/{decision_id}/sync
POST /api/v1/events/invalidation
GET  /api/v1/events/invalidation
GET  /api/v1/decisions
GET  /api/v1/decisions/{decision_id}
GET  /api/v1/decisions/{decision_id}/audit
GET  /api/v1/decisions/{decision_id}/comparison
GET  /api/v1/datahub/health
GET  /api/v1/analytics-agent/health
GET  /api/v1/datahub/agent-registry
POST /api/v1/datahub/agent-registry
GET  /health
```

## Run the full DataHub MCP demo

Python 3.11 is recommended because it is the actively tested DataHub CLI
version. Docker Desktop must be running.

```powershell
cd backend
python -m pip install -e .

# Start DataHub 1.6.
python -m uv tool run --from "acryl-datahub>=1.6,<2" datahub docker quickstart --version v1.6.0 --accept-version-default

# Seed two real dataset entities, descriptions, custom properties, and schemas.
$env:DATAHUB_GMS_URL = "http://localhost:8080"
$env:DATAHUB_GMS_TOKEN = ""
python -m uv run --with "acryl-datahub>=1.6,<2" python ..\scripts\seed_datahub.py

# Enable official DataHub MCP context retrieval and start DecisionGraph.
$env:DATAHUB_MCP_ENABLED = "true"
$env:DATAHUB_GMS_URL = "http://localhost:8080"
python -m uvicorn app.main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000) to use the DecisionGraph
console. From the UI you can run a decision, approve it, trigger invalidation,
create a revalidation revision, and inspect the audit trail.

Every revision pair also exposes a change-impact comparison. The dashboard keeps
the prior and updated context side by side, highlights changed facts and snapshot
paths, provides direct navigation to either immutable record, and explains which
downstream routines must retrieve context, rebuild the recommendation, request
approval, monitor dependencies, or project a new DataHub Document.

The first MCP-backed run may take longer while `uv` prepares the isolated
official `mcp-server-datahub` environment.

To make the reorder calculation with DataHub's Analytics Agent, start the
[open-source Analytics Agent](https://github.com/datahub-project/analytics-agent)
with a configured query engine, then set:

```powershell
$env:ANALYTICS_AGENT_ENABLED = "true"
$env:ANALYTICS_AGENT_URL = "http://localhost:8100"
$env:ANALYTICS_AGENT_ENGINE = "your-configured-engine-name"
```

DecisionGraph creates an Analytics Agent conversation, streams the result,
stores the generated SQL and returned rows, captures the Vega-Lite chart and
context-quality score, and reruns that analysis for each revalidation revision.
A configured failure is surfaced; it never silently becomes fixture output.

To approve the MCP write-back path:

```powershell
$env:DATAHUB_MCP_MUTATIONS_ENABLED = "true"
```

Approval then calls `save_document` with the governed dataset URNs as related
assets and immediately verifies the returned Document with `get_entities`.

The Agent Registry endpoint catalogs DecisionGraph, five REST tools, the generic
governance skill, and both consumed datasets when the installed DataHub SDK
contains `datahub.api.entities.agent`. The released DataHub 1.6 Python SDK used
by the local quickstart does not yet contain those current-main Agent Registry
entities, so the endpoint reports `sdk_unavailable` instead of claiming a
registration. It is ready for a compatible SDK/server release.

Without `DATAHUB_MCP_ENABLED`, decisions use the explicit
`deterministic_fixture` context source. Without `DATAHUB_GMS_URL`, decisions
still run, approve, persist, invalidate, and
record audit history; their projection status is `NOT_CONFIGURED`. Failed
DataHub writes become `RETRY_REQUIRED` and can be retried through the sync
endpoint. Invalidated decisions stay immutable; the revalidation endpoint creates
a new pending revision from freshly retrieved context, and approving that
replacement retires the older record as `SUPERSEDED`.

## Public judge demo

The public judge demo is hosted without billing details through GitHub Pages:

**[Open the DecisionGraph judge demo](https://destr0yering.github.io/decisiongraph/)**

**[Watch the public 2:57 demonstration video](https://youtu.be/uMznzfsk7uw)**

The browser demo intentionally runs without private credentials and labels its
context source as `deterministic_fixture`. It demonstrates the complete
decision, approval, invalidation, revalidation, supersession, and audit workflow
using browser-local storage.

The full local quickstart above is the authoritative live DataHub MCP path. It
uses real governed entities and schemas and projects approved decisions back as
DataHub Documents.

The public page also includes a clearly labeled **recorded live integration
snapshot** from the verified local DataHub 1.6 run. It exposes the MCP context
source and tools, retrieved field counts, the real Analytics Agent conversation
and SQL result, the live 3-to-4-row revalidation, affected routines, native
Document URN, `SYNCED` projection result, related dataset assets, and successful
read-back. The chart and displayed answer are rebound to the authoritative SQL
rows before persistence. This evidence panel does not claim that the
browser-local workflow is connected to DataHub.

The repository also includes a root `Dockerfile` and `render.yaml` for anyone
who prefers a container-hosted demo.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Destr0yering/decisiongraph)

To run the public-demo container locally:

```powershell
docker build -t decisiongraph .
docker run --rm -p 8000:8000 decisiongraph
```

Then open [http://localhost:8000](http://localhost:8000).

Run the automated suite:

```powershell
cd backend
python -m unittest discover -s tests -v
```

The `examples/` directory deliberately separates evidence from illustration:
`live-revalidation-proof.json` records the final live MCP, Analytics Agent,
write-back, and revalidation proof; `decision-record.json` is the earlier
recorded DataHub 1.6 MCP/write-back run; and
`analytics-agent-contract.json` is clearly labeled as a non-live contract
example.

## Build milestones

- [x] Architecture and governing state-machine decisions
- [x] Typed deterministic decision workflow scaffold
- [x] DataHub 1.6 read/write capability spike (native Document + related dataset URN)
- [x] SQLite decision ledger, audit events, and retryable approval projection
- [x] Live approval → DataHub projection → read-back verification
- [x] Revalidation/supersession flow and end-to-end tests
- [x] Dashboard and visual lineage view
- [x] Official DataHub MCP Server context retrieval
- [x] MCP-backed revalidation with persisted context snapshots
- [x] Downstream `get_lineage` and richer entity context snapshots
- [x] DataHub Analytics Agent conversation/SSE integration
- [x] Approval-gated MCP `save_document` with read-back verification
- [x] Agent Context Kit dependency and version-aware Agent Registry adapter
- [x] Generic DataHub Decision Governance skill
- [x] Durable invalidation-event ledger
- [x] Demo video and submission copy
- [x] Public repository and judge-accessible demo URL

See `docs/architecture.md` for the authoritative MVP boundaries.
