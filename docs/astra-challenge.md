# DecisionGraph: Astra challenge revision

DecisionGraph gives operational decisions an evidence trail and a recall workflow. When a forecast changes, the old approval becomes stale; a replacement requires a separate human approval.

## What changed for this challenge

GPT-6 Astra in Codex helped implement the guided browser walkthrough, clearer landing page, static lifecycle regression check, and optional structured evidence reviewer with citation validation. The walkthrough covers calculation, approval, invalidation, rejected stale approval, and a separately approved replacement. Duplicate replacement creation is rejected.

The DataHub integration, Python decision ledger, and recorded DataHub demonstration predate this challenge. The existing video and July 29 integration capture demonstrate that earlier work, not an Astra API run. This entry is a revision of that existing open-source project.

## Try it

Open [the public demo](https://destr0yering.github.io/decisiongraph/) and select **Start the guided demo**. Every action is browser-local with fictional retail fixtures. No purchase, external write, or model request occurs. The registry preserves both versions and their evidence.

## Optional Astra API reviewer

The command-line reviewer sends a bounded evidence packet to the Responses API using `gpt-6-astra`, requests structured output, and rejects unknown evidence citations. Its allowed recommendations are `review_required` and `insufficient_evidence`; it cannot approve or mutate a decision. Citation validation checks reference integrity, not the factual correctness of model reasoning.

From the repository root, with backend dependencies installed and your own `OPENAI_API_KEY` configured:

```console
python scripts/review_with_astra.py --output review.json
```

The default packet uses the existing historical DataHub proof with explicit provenance. Use `--comparison comparison.json` for a supported exported comparison. Only send evidence you are authorized to share with OpenAI. Successful output includes the input hash, model, response ID, capture time, usage, and evidence packet. Do not publish private evidence.

**Verification status:** live API attempts during this revision returned HTTP 429. No successful Astra API capture is claimed or included. The API reviewer remains experimental; the public walkthrough is deterministic. API access and any charges are separate from using Astra in Codex.

## Validation

The Python tests cover decision lifecycle behavior and structured-review validation. The dependency-free JavaScript smoke test exercises the static lifecycle, stale-approval rejection, replacement creation, and duplicate-revalidation rejection:

```console
cd backend
python -m unittest discover -s tests -v
```

```console
node scripts/test-static-demo.cjs
```
