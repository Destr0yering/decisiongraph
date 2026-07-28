# DecisionGraph — Devpost submission package

## Submission fields

### Project name

DecisionGraph

### Tagline

Governed decisions in motion: evidence in, approval gated, traceability out.

### Challenge category

Agents That Do Real Work

### Elevator pitch

DecisionGraph turns an AI recommendation into a governed, durable DataHub
artifact. It reads governed context and lineage through DataHub MCP, asks
DataHub's open-source Analytics Agent to compute the recommendation, records the
SQL and result behind the decision, requires human approval before MCP
write-back, and creates a traceable replacement when source evidence changes.

### Inspiration

AI agents are increasingly capable of recommending operational actions, but the
recommendation is often separated from the governed context that produced it.
That creates four difficult questions: Which data shaped the recommendation?
Who approved it? What action was taken? What happens when the evidence changes?

DecisionGraph was created to make those answers part of the decision itself.
Instead of treating an agent response as disposable text, it treats the response
as a governed object with evidence, lifecycle state, approval history, DataHub
relationships, and recall behavior.

### What it does

DecisionGraph demonstrates a closed decision-governance loop:

1. The agent reads governed entities, schema fields, and downstream lineage
   through the official open-source DataHub MCP Server.
2. DataHub's open-source Analytics Agent performs the reorder calculation and
   returns reproducible SQL, rows, chart output, and context-quality metadata.
3. DecisionGraph creates a recommendation with both a persisted context
   snapshot and the Analytics Agent result, plus explicit dataset URN dependencies.
4. The recommendation remains pending until a person approves it.
5. Approval calls MCP `save_document`, relates the native DataHub Document to
   the source datasets, and verifies the result by read-back.
6. A simulated freshness or quality event identifies affected decisions and
   marks them `REVALIDATION_REQUIRED`.
7. Revalidation fetches fresh DataHub MCP context, reruns Analytics Agent, and
   creates a replacement decision linked through a unique `supersedes`
   relationship.
8. The original decision and its audit history remain intact.
9. A side-by-side revision view preserves easy access to the prior and updated
   context, highlights field-level changes, and explains the effect on each
   downstream workflow routine.

The included demonstration uses governed inventory and Northeast forecast
datasets. The credential-free public workflow is explicitly labeled as a
deterministic fixture. The live path delegates the calculation to DataHub
Analytics Agent and retains its full auditable output.

### How we built it

DecisionGraph is a FastAPI application with a responsive browser console and a
durable SQLite decision ledger.

The DataHub integration has two deliberate boundaries:

- Context reads use DataHub MCP `get_entities`, `list_schema_fields`, and
  `get_lineage`.
- Reorder calculations use the open-source
  `datahub-project/analytics-agent` conversation and SSE APIs.
- Approved decisions use MCP `save_document` and are read back with
  `get_entities`.
- A version-aware Agent Registry adapter catalogs the agent, governance skill,
  REST tools, and consumed datasets when a compatible DataHub SDK is installed.

The service stores workflow state, context provenance, audit events, projection
status, invalidation events, and supersession relationships. Projection failures
become `RETRY_REQUIRED` instead of leaving decisions stuck in an ambiguous
pending state. When MCP mode is enabled, context failures are surfaced rather
than silently replaced with fixture data.

The interface uses a retro-future operations-console visual language to make the
decision lifecycle, provenance, and approval boundary immediately visible.

### Challenges we ran into

The hardest design problem was preserving a trustworthy boundary between
recommendation and action. Approving a decision changes external state, so the
workflow needed durable local state, idempotent projection behavior, and explicit
retry semantics.

Revalidation presented a second challenge. Replaying an old recommendation would
look successful while using stale evidence. DecisionGraph therefore refetches
MCP context before creating a replacement and proves that retrieval in the new
decision record.

Running the complete DataHub quickstart locally also required careful resource
management and startup monitoring. The final implementation was tested against a
live DataHub 1.6 deployment rather than only mocked endpoints.

### Accomplishments that we are proud of

- Completed a real MCP-backed decision flow instead of a metadata-only mock.
- Wrote an approved decision back to DataHub and verified it by readback.
- Integrated DataHub Analytics Agent without coupling DecisionGraph to an LLM
  vendor.
- Added richer entity context and downstream lineage to every live snapshot.
- Created a reusable evidence-bound Decision Governance skill.
- Preserved evidence, approval history, invalidation events, and supersession.
- Ensured MCP failures cannot silently fall back to fixture evidence.
- Added retry-safe handling so failed projections cannot remain stuck.
- Verified the complete workflow through the browser and at a mobile viewport.
- Passed all sixteen automated lifecycle, integration-contract, and reliability tests.
- Packaged the application with its dashboard assets and full setup instructions.

### What we learned

Context is most valuable when it remains attached to the action it informed.
DataHub's graph and MCP interface make it possible for an agent to begin with
governed knowledge, while a write-back artifact lets the next person or agent
inherit the decision instead of reconstructing it.

We also learned that revalidation is not simply rerunning code. It requires a new
context retrieval, an immutable historical record, and an explicit relationship
between the old and new decisions.

### What's next

- Add policy-as-code approval rules alongside human review.
- Subscribe to real DataHub assertions and incident signals.
- Expand from one decision type to cost, quality, access, and model-risk actions.
- Add cryptographic evidence hashes and signed approval identities.
- Support multi-agent review and conflict resolution.
- Generalize the live Analytics Agent calculation to more operational decision types.

### Built with

Python, FastAPI, SQLite, DataHub 1.6, DataHub MCP Server, DataHub Agent Context
Kit, DataHub Analytics Agent, FastMCP, uv, Docker, HTML, CSS, and JavaScript.

## Required public links

Replace these placeholders before submission:

- Project/demo URL: https://destr0yering.github.io/decisiongraph/
- Public Apache-2.0 repository: https://github.com/Destr0yering/decisiongraph
- Public YouTube, Vimeo, or Youku video: `VIDEO_URL_REQUIRED`

## Judge testing instructions

### Fast path

1. Open the project URL.
2. Select **Run Decision**.
3. Inspect the recommendation and evidence. Confirm that the public demo honestly
   reports context source `deterministic_fixture` and MCP tools `None`.
4. Select **Approve** and confirm the workflow becomes `APPROVED` while its
   projection remains `NOT_CONFIGURED` because GitHub Pages has no DataHub
   credentials.
5. Select **Invalidate** and confirm the affected record becomes
   `REVALIDATION_REQUIRED`.
6. Select **Revalidate** and inspect the new pending replacement with freshly
   generated fixture context.
7. Open the audit view and confirm the original history and `supersedes`
   relationship remain visible.
8. Scroll to **Verified DataHub Integration Snapshot**. This clearly labeled
   recorded live-run evidence shows the separate DataHub 1.6 path: official MCP
   tools, retrieved schema-field counts, `SYNCED` Document projection, Document
   URN, two related dataset assets, and successful DataHub read-back.

### Local path

Follow the repository README to start DataHub 1.6, seed the two sample datasets,
enable the official DataHub MCP context provider, and launch DecisionGraph.
In this mode, **Run Decision** reports context source `datahub_mcp_server` and
tools `get_entities`, `list_schema_fields`, and `get_lineage`. With MCP
mutations enabled, approval becomes `SYNCED` and the record includes its native
DataHub Document URN. Analytics Agent output is only claimed when its separately
configured service is enabled.

No paid service or private credential is required for the local quickstart.

## Final compliance checklist

- [x] Project URL uses public GitHub Pages hosting without billing requirements.
- [x] Repository is public.
- [x] Repository contains the full source, assets, examples, and setup instructions.
- [x] Apache License 2.0 is stored in the root `LICENSE` file.
- [x] GitHub identifies the root license as Apache-2.0.
- [ ] Video is publicly visible on YouTube, Vimeo, or Youku.
- [x] Video is shorter than three minutes.
- [x] Video contains visible footage of the working application.
- [x] Video contains no unlicensed music, franchise imagery, or unrelated marks.
- [x] Submission description is in English.
- [x] Sample inputs and decision output are present in `examples/`.
- [x] DataHub MCP use and DataHub write-back are clearly described.
- [ ] All three public URLs replace the placeholders above.

## Optional feedback-prize draft

The self-hosted DataHub MCP workflow was powerful once connected, but local
quickstart users would benefit from a single documented readiness command that
checks GMS health, MCP authentication, enabled tools, and a sample entity lookup.
The current troubleshooting path spans Docker health, GMS reachability, package
startup, and MCP tool behavior. A `datahub mcp doctor` command with actionable
pass/fail output and exact remediation guidance would significantly reduce setup
time and make MCP integrations easier to validate in CI.
