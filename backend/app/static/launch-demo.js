/* Product Hunt walkthrough: all mutations here are confined to the browser sandbox. */
(() => {
  const next = document.getElementById("tourNext");
  const title = document.getElementById("tourTitle");
  const message = document.getElementById("tourMessage");
  const result = document.getElementById("tourResult");
  let step = 0;
  let priorId = null;
  let revisionId = null;
  const sandbox = window.DecisionGraphStaticDemo;
  if (!sandbox) {
    next.disabled = true;
    next.textContent = "Open public sandbox";
    document.getElementById("tourDisclosure").innerHTML = 'This console uses the configured backend. <a href="https://destr0yering.github.io/decisiongraph/">Open the isolated public walkthrough</a> to try fictional data.';
  }

  function progress() {
    document.querySelectorAll("[data-tour-step]").forEach((item) => {
      item.classList.toggle("complete", Number(item.dataset.tourStep) <= step);
    });
  }
  next.addEventListener("click", async () => {
    if (!sandbox) return;
    next.disabled = true;
    try {
      let selected;
      if (step === 0) {
        selected = await sandbox.request("/api/v1/decisions/run", {method:"POST"});
        priorId = selected.id;
        title.textContent = "Three reorder candidates. Approval is still required.";
        message.textContent = "The fictional forecast recommends 80, 70, and 62 units. The evidence is attached. Nothing has been ordered.";
        next.textContent = "Approve this demo decision";
      } else if (step === 1) {
        selected = await sandbox.request(`/api/v1/decisions/${priorId}/approve`, {method:"POST"});
        title.textContent = "Approved against the evidence available at that moment.";
        message.textContent = "Now simulate an upstream forecast change. The old approval must not carry forward.";
        next.textContent = "Change the forecast";
      } else if (step === 2) {
        await sandbox.request("/api/v1/events/invalidation", {method:"POST", body:JSON.stringify({
          asset_urn:"urn:li:dataset:(urn:li:dataPlatform:demo,fiction_retail.northeast_forecast,PROD)", event_type:"FORECAST_UPDATED"})});
        const records = await sandbox.request("/api/v1/decisions");
        selected = records.find((item) => item.id === priorId);
        let blocked = false;
        try { await sandbox.request(`/api/v1/decisions/${priorId}/approve`, {method:"POST"}); }
        catch { blocked = true; }
        if (!blocked) throw new Error("Unexpected state: stale approval was not blocked.");
        title.textContent = "Stale approval blocked.";
        message.textContent = "DecisionGraph marked the decision REVALIDATION_REQUIRED. We tried reusing its approval and the workflow rejected it. The original record is preserved.";
        next.textContent = "Recalculate with new evidence";
      } else if (step === 3) {
        selected = await sandbox.request(`/api/v1/decisions/${priorId}/revalidate`, {method:"POST"});
        revisionId = selected.id;
        title.textContent = "A fresh revision. A separate approval.";
        message.textContent = "The sandbox now has four candidates and an updated forecast horizon. The replacement is pending approval; the old decision is still retained.";
        next.textContent = "Approve the replacement";
        result.hidden = false;
        result.textContent = "3 → 4 candidates · Prior evidence preserved · Stale approval rejected · New approval required";
      } else if (step === 4) {
        selected = await sandbox.request(`/api/v1/decisions/${revisionId}/approve`, {method:"POST"});
        title.textContent = "The old decision is superseded, not erased.";
        message.textContent = "Inspect the registry, side-by-side evidence, and audit trail below. This was a deterministic browser demo; no external system or model was called.";
        next.textContent = "Start another demo";
      } else {
        step = 0;
        result.hidden = true;
        next.textContent = "Start the guided demo";
        title.textContent = "Ready for another decision.";
        message.textContent = "Your previous demo decisions remain in the registry.";
        progress();
        return;
      }
      step += 1;
      progress();
      await refreshState(selected.id);
    } catch (error) {
      message.textContent = error.message;
    } finally { next.disabled = false; }
  });

  document.getElementById("astraProofButton").addEventListener("click", () => {
    const panel = document.getElementById("astraProof");
    panel.hidden = !panel.hidden;
    panel.innerHTML = '<h3>Evidence first. Human approval last.</h3><p>The optional command-line tool sends a bounded evidence packet to Astra, requests a structured explanation, and rejects findings that cite unknown evidence IDs. It cannot approve a decision or change the ledger.</p><p>Citation checks verify references, not whether the model is correct. Live API verification is still pending after HTTP 429 responses. No successful Astra API result is claimed here.</p><p>The guided demo uses fictional, deterministic data. The DataHub recording below documents an earlier integration run.</p>';
  });
})();
