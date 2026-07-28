# DecisionGraph

DecisionGraph gives AI-assisted decisions traceable evidence, approval history,
and recall when the DataHub context they depend on changes. It reads governed
dataset context through the official open-source DataHub MCP Server and writes
approved decision records back as native DataHub Documents.

**Hackathon category:** Agents That Do Real Work

## MVP scope

1. Retrieve dataset metadata and schemas with the official DataHub MCP Server.
2. Create a deterministic, evidence-grounded decision with explicit DataHub URN dependencies.
3. Require approval before it becomes approved.
4. Simulate a freshness or quality event and find every dependent decision.
5. Mark impacted decisions `REVALIDATION_REQUIRED`.
6. Re-fetch DataHub MCP context and link the replacement as a superseding revision.

DataHub remains the source of truth for metadata and lineage. DecisionGraph keeps workflow state, audit history, and retry-safe projections locally, then mirrors supported records and associations back to DataHub.

## Initial API

The FastAPI service is in `backend/`. It does not require an LLM: the agent
workflow is deterministic and its context source is explicit. With
`DATAHUB_MCP_ENABLED=true`, decision creation invokes the official MCP tools
`get_entities` and `list_schema_fields`. When `DATAHUB_GMS_URL` is configured, approval
automatically creates a native DataHub Document related to the decision's source
dataset URNs. Workflow state and audit history are durable in SQLite. The root
route serves a built-in browser dashboard for the live demo workflow.

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
official `mcp-server-datahub` environment. Mutation tools are disabled for this
connection; DecisionGraph uses the MCP server only for governed context reads.

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

The browser demo intentionally runs without private credentials and labels its
context source as `deterministic_fixture`. It demonstrates the complete
decision, approval, invalidation, revalidation, supersession, and audit workflow
using browser-local storage.

The full local quickstart above is the authoritative live DataHub MCP path. It
uses real governed entities and schemas and projects approved decisions back as
DataHub Documents.

The public page also includes a clearly labeled **recorded live integration
snapshot** from the verified local DataHub 1.6 run. It exposes the MCP context
source and tools, retrieved field counts, native Document URN, `SYNCED`
projection result, related dataset assets, and successful read-back. This
evidence panel does not claim that the browser-local workflow is connected to
DataHub.

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
- [x] Durable invalidation-event ledger
- [x] Demo video and submission copy
- [x] Public repository and judge-accessible demo URL

See `docs/architecture.md` for the authoritative MVP boundaries.
