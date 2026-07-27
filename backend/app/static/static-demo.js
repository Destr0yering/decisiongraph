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
    return {
      id: id(),
      title: "Review governed Northeast reorder candidates",
      summary:
        "Evaluate three Northeast inventory candidates against the governed forecast horizon before approval.",
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
        "3 governed Northeast reorder candidates are in scope.",
        "Forecast freshness is FRESH within the 30-day planning horizon.",
        "5 inventory fields and 5 forecast fields support the recommendation.",
        "This public GitHub Pages demo uses an explicit deterministic fixture; run the repository quickstart for live DataHub MCP retrieval and write-back.",
      ],
      context: {
        source: "deterministic_fixture",
        tools: [],
        fetched_at: createdAt,
        facts: {
          candidate_count: 3,
          forecast_freshness: "FRESH",
          inventory_fields: 5,
          forecast_fields: 5,
        },
      },
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
