(function configureStaticJudgeDemo() {
  if (!window.location.hostname.endsWith("github.io")) {
    return;
  }

  const storageKey = "decisiongraph-static-demo-v1";
  const inventoryUrn =
    "urn:li:dataset:(urn:li:dataPlatform:demo,fiction_retail.inventory,PROD)";
  const forecastUrn =
    "urn:li:dataset:(urn:li:dataPlatform:demo,fiction_retail.northeast_forecast,PROD)";

  function emptyStore() {
    return { decisions: [], audits: {}, invalidations: [] };
  }

  function load() {
    try {
      return JSON.parse(window.localStorage.getItem(storageKey)) || emptyStore();
    } catch {
      return emptyStore();
    }
  }

  function save(store) {
    window.localStorage.setItem(storageKey, JSON.stringify(store));
  }

  function now() {
    return new Date().toISOString();
  }

  function id() {
    return window.crypto.randomUUID();
  }

  function audit(store, decisionId, eventType, details = {}) {
    store.audits[decisionId] ||= [];
    store.audits[decisionId].push({
      event_type: eventType,
      created_at: now(),
      details,
    });
  }

  function createDecision(supersedes = null) {
    const createdAt = now();
    const isRevision = Boolean(supersedes);
    return {
      id: id(),
      title: "Review governed Northeast reorder candidates",
      summary:
        isRevision
          ? "Evaluate four Northeast inventory candidates against the refreshed 45-day forecast horizon before approval."
          : "Evaluate three Northeast inventory candidates against the governed 30-day forecast horizon before approval.",
      status: "PENDING_APPROVAL",
      projection_status: "NOT_CONFIGURED",
      projection_error: null,
      datahub_urn: null,
      created_at: createdAt,
      approved_at: null,
      supersedes,
      dependencies: [
        { asset_urn: inventoryUrn, dependency_type: "DATASET_CONTEXT" },
        { asset_urn: forecastUrn, dependency_type: "DATASET_CONTEXT" },
      ],
      evidence: [
        isRevision
          ? "4 governed Northeast reorder candidates are now in scope."
          : "3 governed Northeast reorder candidates are in scope.",
        isRevision
          ? "Forecast freshness is REFRESHED within the updated 45-day planning horizon."
          : "Forecast freshness is FRESH within the 30-day planning horizon.",
        isRevision
          ? "5 inventory fields and 6 forecast fields support the updated recommendation."
          : "5 inventory fields and 5 forecast fields support the recommendation.",
        "This public GitHub Pages demo uses an explicit deterministic fixture; run the repository quickstart for live DataHub MCP retrieval and write-back.",
      ],
      context: {
        source: "deterministic_fixture",
        tools: [],
        fetched_at: createdAt,
        facts: isRevision
          ? [
              "4 governed Northeast reorder candidates are now in scope.",
              "Forecast freshness is REFRESHED for a 45-day horizon.",
              "5 inventory fields and 6 forecast fields were evaluated.",
            ]
          : [
              "3 governed Northeast reorder candidates are in scope.",
              "Forecast freshness is FRESH for a 30-day horizon.",
              "5 inventory fields and 5 forecast fields were evaluated.",
            ],
        snapshot: {
          candidate_count: isRevision ? 4 : 3,
          forecast_freshness: isRevision ? "REFRESHED" : "FRESH",
          planning_horizon_days: isRevision ? 45 : 30,
          inventory_fields: 5,
          forecast_fields: isRevision ? 6 : 5,
        },
      },
    };
  }

  function comparisonFor(store, selected) {
    const prior = selected.supersedes
      ? findDecision(store, selected.supersedes)
      : selected;
    const current = selected.supersedes
      ? selected
      : store.decisions.find((item) => item.supersedes === selected.id);
    if (!current) {
      throw new Error("No prior and updated revision pair exists");
    }
    const changes = [];
    if (prior.summary !== current.summary) {
      changes.push({
        path: "summary",
        change_type: "CHANGED",
        before: prior.summary,
        after: current.summary,
      });
    }
    if (JSON.stringify(prior.context?.facts) !== JSON.stringify(current.context?.facts)) {
      changes.push({
        path: "context.facts",
        change_type: "CHANGED",
        before: prior.context?.facts,
        after: current.context?.facts,
      });
    }
    if (prior.context?.fetched_at !== current.context?.fetched_at) {
      changes.push({
        path: "context.fetched_at",
        change_type: "CHANGED",
        before: prior.context?.fetched_at,
        after: current.context?.fetched_at,
      });
    }
    const priorSnapshot = prior.context?.snapshot || {};
    const currentSnapshot = current.context?.snapshot || {};
    for (const key of new Set([
      ...Object.keys(priorSnapshot),
      ...Object.keys(currentSnapshot),
    ])) {
      if (JSON.stringify(priorSnapshot[key]) !== JSON.stringify(currentSnapshot[key])) {
        changes.push({
          path: `context.snapshot.${key}`,
          change_type: "CHANGED",
          before: priorSnapshot[key],
          after: currentSnapshot[key],
        });
      }
    }
    const contextPaths = changes
      .map((change) => change.path)
      .filter((path) => path.startsWith("context"));
    return {
      prior,
      current,
      changes,
      routine_impacts: [
        {
          routine: "retrieve_context",
          effect: "Use the refreshed governed metadata and schema snapshot instead of the prior retrieval.",
          triggered_by: contextPaths,
        },
        {
          routine: "build_recommendation",
          effect: "Recompute the recommendation and evidence from the updated context; do not replay the prior conclusion.",
          triggered_by: contextPaths,
        },
        {
          routine: "request_human_approval",
          effect: "Require a fresh approval because the evidence-bearing decision revision changed.",
          triggered_by: changes.map((change) => change.path),
        },
        {
          routine: "project_datahub_document",
          effect: "Keep the prior projection immutable and create a new projection only after approval.",
          triggered_by: ["supersedes"],
        },
      ],
    };
  }

  function pathFor(url) {
    const path = new URL(url, window.location.href).pathname;
    const apiIndex = path.indexOf("/api/");
    if (apiIndex >= 0) return path.slice(apiIndex);
    return path.endsWith("/health") ? "/health" : path;
  }

  function findDecision(store, decisionId) {
    const decision = store.decisions.find((item) => item.id === decisionId);
    if (!decision) throw new Error("Decision not found");
    return decision;
  }

  async function request(url, options = {}) {
    const path = pathFor(url);
    const method = (options.method || "GET").toUpperCase();
    const store = load();

    if (method === "GET" && path === "/health") {
      return { status: "ok", mode: "static-demo" };
    }
    if (method === "GET" && path === "/api/v1/datahub/health") {
      return { status: "not_configured" };
    }
    if (method === "GET" && path === "/api/v1/decisions") {
      return [...store.decisions].reverse();
    }
    if (method === "GET" && path === "/api/v1/events/invalidation") {
      return [...store.invalidations].reverse();
    }

    const auditMatch = path.match(/^\/api\/v1\/decisions\/([^/]+)\/audit$/);
    if (method === "GET" && auditMatch) {
      return store.audits[auditMatch[1]] || [];
    }

    const comparisonMatch = path.match(
      /^\/api\/v1\/decisions\/([^/]+)\/comparison$/
    );
    if (method === "GET" && comparisonMatch) {
      return comparisonFor(store, findDecision(store, comparisonMatch[1]));
    }

    if (method === "POST" && path === "/api/v1/decisions/run") {
      const decision = createDecision();
      store.decisions.push(decision);
      audit(store, decision.id, "DECISION_CREATED", {
        context_source: "deterministic_fixture",
        demo_surface: "github_pages",
      });
      save(store);
      return decision;
    }

    const actionMatch = path.match(
      /^\/api\/v1\/decisions\/([^/]+)\/(approve|revalidate|sync)$/
    );
    if (method === "POST" && actionMatch) {
      const [, decisionId, action] = actionMatch;
      const decision = findDecision(store, decisionId);

      if (action === "approve") {
        if (decision.status !== "PENDING_APPROVAL") {
          throw new Error("Only pending decisions can be approved");
        }
        decision.status = "APPROVED";
        decision.approved_at = now();
        decision.projection_status = "NOT_CONFIGURED";
        audit(store, decision.id, "DECISION_APPROVED", {
          projection: "NOT_CONFIGURED",
        });
        if (decision.supersedes) {
          const previous = findDecision(store, decision.supersedes);
          previous.status = "SUPERSEDED";
          audit(store, previous.id, "DECISION_SUPERSEDED", {
            replacement_id: decision.id,
          });
        }
        save(store);
        return decision;
      }

      if (action === "revalidate") {
        if (decision.status !== "REVALIDATION_REQUIRED") {
          throw new Error("Decision must require revalidation");
        }
        const replacement = createDecision(decision.id);
        store.decisions.push(replacement);
        audit(store, replacement.id, "REVALIDATION_CREATED", {
          supersedes: decision.id,
          context_source: "deterministic_fixture",
        });
        save(store);
        return replacement;
      }

      if (action === "sync") {
        decision.projection_status = "NOT_CONFIGURED";
        audit(store, decision.id, "PROJECTION_NOT_CONFIGURED", {
          reason: "Static judge demo has no external DataHub connection",
        });
        save(store);
        return decision;
      }
    }

    if (method === "POST" && path === "/api/v1/events/invalidation") {
      const payload = JSON.parse(options.body || "{}");
      const event = {
        id: id(),
        asset_urn: payload.asset_urn,
        event_type: payload.event_type || "DATASET_STALE",
        severity: payload.severity || "HIGH",
        created_at: now(),
      };
      store.invalidations.push(event);
      const impacted = [];
      for (const decision of store.decisions) {
        if (
          decision.status === "APPROVED" &&
          decision.dependencies.some(
            (dependency) => dependency.asset_urn === event.asset_urn
          )
        ) {
          decision.status = "REVALIDATION_REQUIRED";
          impacted.push(decision);
          audit(store, decision.id, "DECISION_INVALIDATED", {
            event_id: event.id,
            event_type: event.event_type,
            asset_urn: event.asset_urn,
          });
        }
      }
      save(store);
      return impacted;
    }

    throw new Error(`Static demo route is not implemented: ${method} ${path}`);
  }

  window.DecisionGraphStaticDemo = { request };
})();
