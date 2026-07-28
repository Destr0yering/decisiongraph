# DecisionGraph MVP architecture

## Boundary

DecisionGraph is a modular monolith:

```text
Dashboard -> FastAPI API -> Decision workflow + impact analyzer -> local ledger
                            |                    |            |
                            |                    +-- MCP client+-> official
                            |                                  |   DataHub MCP
                            +---- DataHub adapter/outbox -------+-> DataHub
```

DataHub is authoritative for discovered metadata, schemas, asset lineage,
ownership, and governance signals. DecisionGraph retrieves that context through
the official open-source DataHub MCP Server. DecisionGraph is authoritative for
decision lifecycle, approval, immutable MCP context snapshots, invalidation
events, and audit history. Only supported, queryable projections are written to
DataHub.

When a dependency changes, the previously approved decision is preserved as-is.
It transitions to `REVALIDATION_REQUIRED`, a fresh revision is created with a
`supersedes` pointer, and that replacement must be approved before the older
record is retired as `SUPERSEDED`.

## Demo guarantees

- MCP mode invokes the official `get_entities` and `list_schema_fields` tools.
- Offline mode is explicit and records `deterministic_fixture` as its context source.
- Evidence contains concise facts, assumptions, warnings, and citations—never private reasoning.
- Approval is a separate human action.
- An invalidation event is append-only and targets recorded dependency edges.
- Revalidation retrieves fresh MCP context and creates a new immutable decision
  revision; it never mutates the old evidence.
- Every revision pair exposes the complete prior and current records, field-level
  context changes, and an explicit map from those changes to affected workflow
  routines.
- Every invalidation signal is durable even when it impacts zero decisions.

## Revision comparison and routine impact

`GET /api/v1/decisions/{id}/comparison` accepts either side of a revision pair.
It returns:

- the complete immutable prior decision;
- the complete updated decision;
- highlighted changes to the summary, context source, MCP tools, retrieval time,
  facts, nested snapshot paths, and dependencies;
- the downstream effect on context retrieval, recommendation generation,
  dependency monitoring, human approval, and DataHub Document projection.

The comparison is derived from the persisted records. The dashboard does not
invent a change narrative independently of the ledger.

## DataHub integration spike

Before claiming a final mapping, validate it against the target DataHub release:

1. Read an asset, schema, lineage, owner, and quality signal.
2. Create an agent-run projection using supported DataFlow/DataJob capabilities.
3. Publish a compact Decision Document and supported associations to its source asset.
4. Re-read the projection and verify the relationship in the DataHub UI/API.

If custom relationships are unavailable, retain the precise dependency edges in DecisionGraph and project a supported Document plus source URNs to DataHub.

## Verified DataHub 1.6 mapping

The local integration spike verified the following against DataHub 1.6:

- `createDocument` persists a native decision projection.
- `relatedAssets` preserves a relationship to a dataset URN.
- `showInGlobalContext: false` keeps the decision out of global context while leaving it accessible through its related asset.
- The `document` query reads the projection and relationship back successfully.
- The official self-hosted MCP Server reads both demo datasets through
  `get_entities`.
- `list_schema_fields` returns five governed fields for each demo dataset.

For an 8 GB Windows host, the verification stack uses the backend-only Compose
profile with reduced GMS, Kafka, and OpenSearch heaps.

## Approval and projection behavior

Approval and DataHub projection are separate persisted facts:

1. A pending decision transitions to `APPROVED` in SQLite.
2. A projection attempt is recorded as `PENDING`.
3. A successful write records the DataHub Document URN and `SYNCED`.
4. An unavailable or rejected DataHub write records `RETRY_REQUIRED` and a
   sanitized error while preserving the approved decision.
5. `POST /api/v1/decisions/{id}/sync` safely retries the projection.

This prevents an external outage from losing an approval and provides a small,
inspectable outbox state for the hackathon MVP.
