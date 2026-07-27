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
    void renderAudit(null);
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
  void renderAudit(decision);
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

async function boot() {
  await Promise.all([
    refreshState(),
    loadDataHubHealth(),
    loadAppHealth(),
  ]);
}

void boot();
