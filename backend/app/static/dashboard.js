const state = {
  decisions: [],
  selectedId: null,
};

const baseUrl = new URL(".", window.location.href);

function apiUrl(path) {
  return new URL(path, baseUrl).toString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const elements = {
  modeLabel: document.getElementById("modeLabel"),
  datahubStatus: document.getElementById("datahubStatus"),
  decisionCount: document.getElementById("decisionCount"),
  attentionCount: document.getElementById("attentionCount"),
  queueSummary: document.getElementById("queueSummary"),
  decisionList: document.getElementById("decisionList"),
  decisionTitle: document.getElementById("decisionTitle"),
  decisionStatusChip: document.getElementById("decisionStatusChip"),
  decisionSummary: document.getElementById("decisionSummary"),
  projectionStatus: document.getElementById("projectionStatus"),
  supersedesValue: document.getElementById("supersedesValue"),
  contextSource: document.getElementById("contextSource"),
  contextTools: document.getElementById("contextTools"),
  projectionError: document.getElementById("projectionError"),
  dependencyList: document.getElementById("dependencyList"),
  evidenceList: document.getElementById("evidenceList"),
  auditList: document.getElementById("auditList"),
  auditCount: document.getElementById("auditCount"),
  runDecisionButton: document.getElementById("runDecisionButton"),
  refreshButton: document.getElementById("refreshButton"),
  invalidateButton: document.getElementById("invalidateButton"),
  approveButton: document.getElementById("approveButton"),
  revalidateButton: document.getElementById("revalidateButton"),
  syncButton: document.getElementById("syncButton"),
  proofDisclosure: document.getElementById("proofDisclosure"),
  proofDataHubVersion: document.getElementById("proofDataHubVersion"),
  proofContextSource: document.getElementById("proofContextSource"),
  proofTools: document.getElementById("proofTools"),
  proofSchemaFields: document.getElementById("proofSchemaFields"),
  proofProjectionStatus: document.getElementById("proofProjectionStatus"),
  proofReadBack: document.getElementById("proofReadBack"),
  proofAnalyticsAgent: document.getElementById("proofAnalyticsAgent"),
  proofRowChange: document.getElementById("proofRowChange"),
  proofRoutineCount: document.getElementById("proofRoutineCount"),
  proofDocumentUrn: document.getElementById("proofDocumentUrn"),
  proofContextFacts: document.getElementById("proofContextFacts"),
  proofRelatedAssets: document.getElementById("proofRelatedAssets"),
  comparisonSummary: document.getElementById("comparisonSummary"),
  comparisonEmpty: document.getElementById("comparisonEmpty"),
  comparisonContent: document.getElementById("comparisonContent"),
  viewPriorButton: document.getElementById("viewPriorButton"),
  viewCurrentButton: document.getElementById("viewCurrentButton"),
  priorRevisionId: document.getElementById("priorRevisionId"),
  currentRevisionId: document.getElementById("currentRevisionId"),
  priorRevisionTitle: document.getElementById("priorRevisionTitle"),
  currentRevisionTitle: document.getElementById("currentRevisionTitle"),
  priorRevisionSummary: document.getElementById("priorRevisionSummary"),
  currentRevisionSummary: document.getElementById("currentRevisionSummary"),
  priorRevisionFacts: document.getElementById("priorRevisionFacts"),
  currentRevisionFacts: document.getElementById("currentRevisionFacts"),
  changeList: document.getElementById("changeList"),
  routineImpactList: document.getElementById("routineImpactList"),
  analysisSource: document.getElementById("analysisSource"),
  analysisQuality: document.getElementById("analysisQuality"),
  analysisConversation: document.getElementById("analysisConversation"),
  analysisRows: document.getElementById("analysisRows"),
  analysisAnswer: document.getElementById("analysisAnswer"),
  analysisSql: document.getElementById("analysisSql"),
  agentRegistryStatus: document.getElementById("agentRegistryStatus"),
  agentRegistryDetail: document.getElementById("agentRegistryDetail"),
  agentRegistryUrn: document.getElementById("agentRegistryUrn"),
  agentSkillUrn: document.getElementById("agentSkillUrn"),
  agentToolCount: document.getElementById("agentToolCount"),
  registerAgentButton: document.getElementById("registerAgentButton"),
  replayLiveProofButton: document.getElementById("replayLiveProofButton"),
  proofReplay: document.getElementById("proofReplay"),
  proofReplayStatus: document.getElementById("proofReplayStatus"),
  replayContextDetail: document.getElementById("replayContextDetail"),
  replayAnalyticsDetail: document.getElementById("replayAnalyticsDetail"),
  replayRevalidationDetail: document.getElementById("replayRevalidationDetail"),
  replayProjectionDetail: document.getElementById("replayProjectionDetail"),
  replayVerificationDetail: document.getElementById("replayVerificationDetail"),
};

function statusPill(status) {
  const safeStatus = escapeHtml(status);
  return `<span class="status-pill status-${safeStatus}">${safeStatus.replaceAll("_", " ")}</span>`;
}

function formatTime(value) {
  if (!value) {
    return "Pending";
  }
  return new Date(value).toLocaleString();
}

function formatChangeValue(value) {
  if (value === null || value === undefined) {
    return "None";
  }
  const rendered =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return rendered.length > 600 ? `${rendered.slice(0, 597)}…` : rendered;
}

function formatComparisonValue(path, value) {
  if (path === "analysis.rows" && Array.isArray(value)) {
    const rows = value.map(
      (row) =>
        `${row.product_id}: on hand ${row.on_hand_units}, forecast ${row.forecast_units}, reorder ${row.recommended_reorder_quantity}`
    );
    return `${value.length} verified SQL rows\n${rows.join("\n")}`;
  }
  return formatChangeValue(value);
}

function contextFacts(decision) {
  const facts = decision.context?.facts;
  if (Array.isArray(facts)) {
    return facts;
  }
  if (facts && typeof facts === "object") {
    return Object.entries(facts).map(
      ([key, value]) => `${key.replaceAll("_", " ")}: ${value}`
    );
  }
  return decision.evidence || [];
}

function selectedDecision() {
  return state.decisions.find((decision) => decision.id === state.selectedId) ?? null;
}

async function fetchJson(url, options) {
  if (window.DecisionGraphStaticDemo) {
    return window.DecisionGraphStaticDemo.request(url, options);
  }
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function renderDecisionList() {
  elements.decisionCount.textContent = String(state.decisions.length);
  const attention = state.decisions.filter(
    (decision) =>
      decision.status === "REVALIDATION_REQUIRED" ||
      decision.projection_status === "RETRY_REQUIRED" ||
      decision.status === "PENDING_APPROVAL"
  ).length;
  elements.attentionCount.textContent = String(attention);
  elements.queueSummary.textContent =
    state.decisions.length === 0 ? "No records" : `${state.decisions.length} tracked`;

  if (state.decisions.length === 0) {
    elements.decisionList.innerHTML =
      '<div class="empty-state">No decisions yet. Use "Run Decision" to seed the workflow.</div>';
    return;
  }

  elements.decisionList.innerHTML = state.decisions
    .map((decision) => {
      const activeClass = decision.id === state.selectedId ? "active" : "";
      return `
        <button class="decision-row ${activeClass}" data-id="${decision.id}">
          <div class="decision-top">
            <span class="decision-title">${escapeHtml(decision.title)}</span>
            ${statusPill(decision.status)}
          </div>
          <div class="decision-bottom">
            <span>${escapeHtml(decision.projection_status.replaceAll("_", " "))}</span>
            <span>${escapeHtml(formatTime(decision.approved_at || decision.created_at))}</span>
          </div>
        </button>
      `;
    })
    .join("");

  for (const button of elements.decisionList.querySelectorAll("[data-id]")) {
    button.addEventListener("click", () => {
      state.selectedId = button.dataset.id;
      render();
    });
  }
}

async function renderAudit(decision) {
  if (!decision) {
    elements.auditCount.textContent = "0 events";
    elements.auditList.innerHTML =
      '<div class="empty-state">Select a decision to inspect its lifecycle trace.</div>';
    return;
  }

  const requestedId = decision.id;
  const audit = await fetchJson(apiUrl(`api/v1/decisions/${requestedId}/audit`));
  if (state.selectedId !== requestedId) {
    return;
  }
  elements.auditCount.textContent = `${audit.length} events`;
  elements.auditList.innerHTML = audit
    .map((event) => {
      const details = Object.keys(event.details || {}).length
        ? `<div class="audit-details">${Object.entries(event.details)
            .map(
              ([key, value]) =>
                `<div>${escapeHtml(key)}: ${escapeHtml(value)}</div>`
            )
            .join("")}</div>`
        : "";
      return `
        <article class="audit-row">
          <div class="audit-top">
            <span class="audit-event">${escapeHtml(event.event_type)}</span>
            <span class="audit-meta">${escapeHtml(formatTime(event.created_at))}</span>
          </div>
          ${details}
        </article>
      `;
    })
    .join("");
}

async function renderComparison(decision) {
  const replacement = decision
    ? state.decisions.find((item) => item.supersedes === decision.id)
    : null;
  const hasPair = Boolean(decision?.supersedes || replacement);
  elements.comparisonEmpty.hidden = hasPair;
  elements.comparisonContent.hidden = !hasPair;
  elements.comparisonSummary.textContent = hasPair
    ? "Loading revision pair"
    : "No revision pair";
  if (!hasPair) {
    return;
  }

  const requestedId = decision.id;
  try {
    const comparison = await fetchJson(
      apiUrl(`api/v1/decisions/${requestedId}/comparison`)
    );
    if (state.selectedId !== requestedId) {
      return;
    }
    const { prior, current, changes, routine_impacts: routineImpacts } = comparison;
    const changeLabel = changes.length === 1 ? "change" : "changes";
    const routineLabel = routineImpacts.length === 1 ? "routine" : "routines";
    elements.comparisonSummary.textContent =
      `${changes.length} ${changeLabel} · ${routineImpacts.length} ${routineLabel}`;
    elements.priorRevisionId.textContent = prior.id.slice(0, 8);
    elements.priorRevisionId.title = prior.id;
    elements.currentRevisionId.textContent = current.id.slice(0, 8);
    elements.currentRevisionId.title = current.id;
    elements.priorRevisionTitle.textContent = prior.title;
    elements.currentRevisionTitle.textContent = current.title;
    elements.priorRevisionSummary.textContent = prior.summary;
    elements.currentRevisionSummary.textContent = current.summary;
    elements.priorRevisionFacts.innerHTML = contextFacts(prior)
      .map((fact) => `<li>${escapeHtml(fact)}</li>`)
      .join("");
    elements.currentRevisionFacts.innerHTML = contextFacts(current)
      .map((fact) => `<li>${escapeHtml(fact)}</li>`)
      .join("");
    const changePriority = new Map([
      ["analysis.rows", 0],
      ["context.facts", 1],
      ["summary", 2],
    ]);
    const orderedChanges = [...changes].sort(
      (left, right) =>
        (changePriority.get(left.path) ?? 10) -
        (changePriority.get(right.path) ?? 10)
    );
    elements.changeList.innerHTML = orderedChanges.length
      ? orderedChanges
          .map(
            (change) => `
              <article class="change-row">
                <div class="change-path">${escapeHtml(change.path)}</div>
                <div class="change-values">
                  <div class="change-before"><strong>Prior</strong><br>${escapeHtml(formatComparisonValue(change.path, change.before))}</div>
                  <div class="change-after"><strong>Updated</strong><br>${escapeHtml(formatComparisonValue(change.path, change.after))}</div>
                </div>
              </article>
            `
          )
          .join("")
      : '<div class="empty-state">No evidence-bearing fields changed.</div>';
    elements.routineImpactList.innerHTML = routineImpacts
      .map(
        (impact) => `
          <article class="routine-row">
            <div class="routine-name">${escapeHtml(impact.routine)}</div>
            <p>${escapeHtml(impact.effect)}</p>
            <div class="routine-trigger">Triggered by: ${escapeHtml(impact.triggered_by.join(", "))}</div>
          </article>
        `
      )
      .join("");
    elements.viewPriorButton.onclick = () => {
      state.selectedId = prior.id;
      render();
    };
    elements.viewCurrentButton.onclick = () => {
      state.selectedId = current.id;
      render();
    };
  } catch (error) {
    elements.comparisonSummary.textContent = "Comparison unavailable";
    elements.comparisonContent.hidden = true;
    elements.comparisonEmpty.hidden = false;
    elements.comparisonEmpty.textContent = error.message;
  }
}

function renderDecisionDetail() {
  const decision = selectedDecision();
  if (!decision) {
    elements.decisionTitle.textContent = "Awaiting selection";
    elements.decisionStatusChip.textContent = "Idle";
    elements.decisionSummary.textContent = "Run a decision to begin the demo workflow.";
    elements.projectionStatus.textContent = "NOT_CONFIGURED";
    elements.supersedesValue.textContent = "None";
    elements.contextSource.textContent = "Not loaded";
    elements.contextTools.textContent = "None";
    elements.approveButton.disabled = true;
    elements.revalidateButton.disabled = true;
    elements.syncButton.disabled = true;
    elements.invalidateButton.disabled = true;
    elements.projectionError.textContent = "";
    elements.dependencyList.innerHTML =
      '<div class="empty-state">Dependency trace appears here.</div>';
    elements.evidenceList.innerHTML = "";
    elements.analysisSource.textContent = "Not run";
    elements.analysisQuality.textContent = "Not assessed";
    elements.analysisConversation.textContent = "None";
    elements.analysisRows.textContent = "0";
    elements.analysisAnswer.textContent = "No analytics result is attached.";
    elements.analysisSql.textContent = "-- SQL appears here";
    void renderAudit(null);
    void renderComparison(null);
    return;
  }

  elements.decisionTitle.textContent = decision.title;
  elements.decisionStatusChip.innerHTML = statusPill(decision.status);
  elements.decisionSummary.textContent = decision.summary;
  elements.projectionStatus.textContent = decision.projection_status;
  elements.supersedesValue.textContent = decision.supersedes || "None";
  elements.contextSource.textContent =
    decision.context?.source?.replaceAll("_", " ") || "Legacy record";
  elements.contextTools.textContent =
    decision.context?.tools?.join(", ") || "None";
  elements.projectionError.textContent = decision.projection_error || "";
  elements.approveButton.disabled = decision.status !== "PENDING_APPROVAL";
  elements.revalidateButton.disabled =
    decision.status !== "REVALIDATION_REQUIRED";
  elements.syncButton.disabled = decision.status !== "APPROVED";
  elements.invalidateButton.disabled =
    decision.status !== "APPROVED" || !decision.dependencies.length;
  elements.dependencyList.innerHTML = decision.dependencies
    .map(
      (dependency) => `
        <article class="dependency-card">
          <div class="dependency-type">${escapeHtml(dependency.dependency_type)}</div>
          <div class="dependency-urn">${escapeHtml(dependency.asset_urn)}</div>
        </article>
      `
    )
    .join("");
  elements.evidenceList.innerHTML = decision.evidence
    .map((fact) => `<li>${escapeHtml(fact)}</li>`)
    .join("");
  const analysis = decision.analysis;
  elements.analysisSource.textContent =
    analysis?.source?.replaceAll("_", " ") || "Not run";
  elements.analysisQuality.textContent =
    analysis?.context_quality?.label || "Not assessed";
  elements.analysisConversation.textContent =
    analysis?.conversation_id || "Fixture";
  elements.analysisRows.textContent = String(analysis?.rows?.length || 0);
  elements.analysisAnswer.textContent =
    analysis?.answer || "No analytics result is attached.";
  elements.analysisSql.textContent =
    analysis?.sql || "-- SQL was not recorded";
  void renderAudit(decision);
  void renderComparison(decision);
}

function render() {
  renderDecisionList();
  renderDecisionDetail();
}

async function refreshState(preferredId = state.selectedId) {
  state.decisions = await fetchJson(apiUrl("api/v1/decisions"));
  state.selectedId =
    preferredId && state.decisions.some((decision) => decision.id === preferredId)
      ? preferredId
      : state.decisions[0]?.id ?? null;
  render();
}

async function loadDataHubHealth() {
  try {
    const payload = await fetchJson(apiUrl("api/v1/datahub/health"));
    elements.datahubStatus.textContent =
      payload.status === "connected" ? "DataHub connected" : "DataHub not configured";
  } catch (error) {
    elements.datahubStatus.textContent = error.message;
  }
}

async function loadAppHealth() {
  const payload = await fetchJson(apiUrl("health"));
  elements.modeLabel.textContent =
    payload.mode === "datahub-mcp"
      ? "DataHub MCP agent"
      : payload.mode === "static-demo"
        ? "Static judge demo"
        : "Deterministic demo";
}

function renderAgentRegistry(payload) {
  const registered =
    payload.status === "registered" || Boolean(payload.agent_urn);
  elements.agentRegistryStatus.textContent = registered
    ? "Registered"
    : payload.status === "sdk_unavailable"
      ? "SDK unavailable"
      : "Not registered";
  elements.agentRegistryDetail.textContent =
    payload.detail ||
    (registered
      ? "DecisionGraph, its governance skill, tools, and consumed datasets are cataloged in DataHub."
      : "Ready to register DecisionGraph when DataHub is connected.");
  elements.agentRegistryUrn.textContent = payload.agent_urn || "—";
  elements.agentSkillUrn.textContent = payload.skill_urn || "—";
  elements.agentToolCount.textContent = String(payload.tool_urns?.length || 0);
  elements.registerAgentButton.disabled =
    payload.status === "sdk_unavailable" || registered;
}

async function loadAgentRegistry() {
  try {
    const payload = await fetchJson(apiUrl("api/v1/datahub/agent-registry"));
    renderAgentRegistry(payload);
  } catch (error) {
    elements.agentRegistryStatus.textContent = error.message;
  }
}

async function loadIntegrationProof() {
  try {
    const response = await fetch(apiUrl("assets/live-revalidation-proof.json"));
    if (!response.ok) {
      throw new Error(`Verification snapshot unavailable (${response.status})`);
    }
    const proof = await response.json();
    const fieldTotal = proof.datasets.reduce(
      (total, dataset) => total + dataset.schema_field_count,
      0
    );
    elements.proofDisclosure.textContent = proof.disclosure;
    elements.proofDataHubVersion.textContent = `v${proof.datahub_version}`;
    elements.proofContextSource.textContent = proof.context_source;
    elements.proofTools.textContent = proof.mcp_tools.join(" + ");
    elements.proofSchemaFields.textContent =
      `${fieldTotal} across ${proof.datasets.length} datasets`;
    elements.proofProjectionStatus.textContent = proof.projection_status;
    elements.proofReadBack.textContent = proof.read_back_verified
      ? "VERIFIED"
      : "NOT VERIFIED";
    elements.proofAnalyticsAgent.textContent =
      `${proof.analytics.source} · ${proof.analytics.engine}`;
    elements.proofRowChange.textContent =
      `${proof.analytics.prior_row_count} → ${proof.analytics.updated_row_count} SQL rows`;
    elements.proofRoutineCount.textContent =
      `${proof.lifecycle.affected_routines.length} routines`;
    elements.proofDocumentUrn.textContent = proof.datahub_document_urn;
    elements.proofContextFacts.innerHTML = proof.context_facts
      .map((fact) => `<li>${escapeHtml(fact)}</li>`)
      .join("");
    elements.proofRelatedAssets.innerHTML = proof.related_assets
      .map(
        (assetUrn) => `
          <div class="dependency-card">
            <div class="dependency-type">Dataset relationship</div>
            <div class="dependency-urn">${escapeHtml(assetUrn)}</div>
          </div>
        `
      )
      .join("");
  } catch (error) {
    elements.proofDisclosure.textContent = error.message;
  }
}

function replayDelay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function setReplayStage(stage, status) {
  const step = document.querySelector(`[data-replay-stage="${stage}"]`);
  step.classList.remove("active", "complete");
  if (status) {
    step.classList.add(status);
  }
}

async function fetchLiveProof() {
  const response = await fetch(
    `${apiUrl("assets/live-revalidation-proof.json")}?replay=${Date.now()}`,
    { cache: "no-store" }
  );
  if (!response.ok) {
    throw new Error(`Live proof unavailable (${response.status})`);
  }
  return response.json();
}

async function replayLiveProof() {
  elements.replayLiveProofButton.disabled = true;
  elements.proofReplay.hidden = false;
  elements.proofReplayStatus.textContent =
    "Refetching the published live-revalidation-proof.json artifact…";
  ["context", "analytics", "revalidation", "projection", "verification"].forEach(
    (stage) => setReplayStage(stage, "")
  );

  try {
    const proof = await fetchLiveProof();
    const fieldTotal = proof.datasets.reduce(
      (total, dataset) => total + dataset.schema_field_count,
      0
    );

    setReplayStage("context", "active");
    elements.proofReplayStatus.textContent = "Stage 1 of 5 · Governed context";
    elements.replayContextDetail.textContent =
      `${proof.context_source}; ${fieldTotal} schema fields across ` +
      `${proof.datasets.length} datasets via ${proof.mcp_tools.slice(0, 3).join(", ")}.`;
    await replayDelay(550);
    setReplayStage("context", "complete");

    setReplayStage("analytics", "active");
    elements.proofReplayStatus.textContent = "Stage 2 of 5 · Reproducible SQL result";
    const newRow = proof.analytics.new_row;
    elements.replayAnalyticsDetail.textContent =
      `${proof.analytics.prior_row_count} → ${proof.analytics.updated_row_count} rows; ` +
      `${newRow.product_id} adds ${newRow.recommended_reorder_quantity} reorder units.`;
    await replayDelay(550);
    setReplayStage("analytics", "complete");

    setReplayStage("revalidation", "active");
    elements.proofReplayStatus.textContent = "Stage 3 of 5 · Change and routine impact";
    elements.replayRevalidationDetail.textContent =
      `${proof.lifecycle.highlighted_change_count} highlighted changes affect ` +
      `${proof.lifecycle.affected_routines.length} routines; prior record is ` +
      `${proof.lifecycle.prior_status}, replacement is ${proof.lifecycle.replacement_status}.`;
    await replayDelay(550);
    setReplayStage("revalidation", "complete");

    setReplayStage("projection", "active");
    elements.proofReplayStatus.textContent = "Stage 4 of 5 · Approval-gated write-back";
    elements.replayProjectionDetail.textContent =
      `${proof.projection_status} via save_document; ${proof.related_assets.length} ` +
      `related dataset assets attached to ${proof.datahub_document_urn}.`;
    await replayDelay(550);
    setReplayStage("projection", "complete");

    setReplayStage("verification", "active");
    elements.proofReplayStatus.textContent = "Stage 5 of 5 · Verified read-back";
    elements.replayVerificationDetail.textContent =
      `${proof.read_back_verified ? "Read-back verified" : "Read-back not verified"}; ` +
      `${proof.automated_tests_passed} automated tests recorded as passing.`;
    await replayDelay(550);
    setReplayStage("verification", "complete");
    elements.proofReplayStatus.textContent =
      `Replay complete · captured ${new Date(proof.verified_at).toLocaleString()}`;
  } catch (error) {
    elements.proofReplayStatus.textContent = error.message;
  } finally {
    elements.replayLiveProofButton.disabled = false;
  }
}

async function act(label, action) {
  try {
    elements.datahubStatus.textContent = label;
    const result = await action();
    await refreshState(result?.id || state.selectedId);
    await loadDataHubHealth();
  } catch (error) {
    elements.datahubStatus.textContent = error.message;
  }
}

elements.runDecisionButton.addEventListener("click", () =>
  act("Creating decision", () =>
    fetchJson(apiUrl("api/v1/decisions/run"), { method: "POST" })
  )
);

elements.refreshButton.addEventListener("click", () => act("Refreshing", () => refreshState()));

elements.approveButton.addEventListener("click", () => {
  const decision = selectedDecision();
  if (!decision) return;
  void act("Approving decision", () =>
    fetchJson(apiUrl(`api/v1/decisions/${decision.id}/approve`), { method: "POST" })
  );
});

elements.revalidateButton.addEventListener("click", () => {
  const decision = selectedDecision();
  if (!decision) return;
  void act("Creating replacement decision", () =>
    fetchJson(apiUrl(`api/v1/decisions/${decision.id}/revalidate`), { method: "POST" })
  );
});

elements.syncButton.addEventListener("click", () => {
  const decision = selectedDecision();
  if (!decision) return;
  void act("Syncing to DataHub", () =>
    fetchJson(apiUrl(`api/v1/decisions/${decision.id}/sync`), { method: "POST" })
  );
});

elements.invalidateButton.addEventListener("click", () => {
  const decision = selectedDecision();
  if (!decision || !decision.dependencies.length) return;
  const firstDependency = decision.dependencies[0];
  void act("Triggering invalidation", () =>
    fetchJson(apiUrl("api/v1/events/invalidation"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_urn: firstDependency.asset_urn,
        event_type: "DATASET_STALE",
      }),
    })
  );
});

elements.registerAgentButton.addEventListener("click", () =>
  act("Registering DecisionGraph in DataHub", async () => {
    const payload = await fetchJson(apiUrl("api/v1/datahub/agent-registry"), {
      method: "POST",
    });
    renderAgentRegistry(payload);
    return selectedDecision();
  })
);

elements.replayLiveProofButton.addEventListener("click", () => {
  void replayLiveProof();
});

async function boot() {
  await Promise.all([
    refreshState(),
    loadDataHubHealth(),
    loadAppHealth(),
    loadIntegrationProof(),
    loadAgentRegistry(),
  ]);
}

void boot();
