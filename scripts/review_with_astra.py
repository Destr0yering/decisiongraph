"""Generate one evidence-cited review; keys remain in the invoking environment.

python scripts/review_with_astra.py --env-file ../.env.local --output artifacts/astra-review.json
python scripts/review_with_astra.py --comparison comparison.json --output review.json
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.astra_review import ReviewUnavailable, packet_from_comparison, review_packet


def historical_packet():
    proof = json.loads((ROOT / "examples/live-revalidation-proof.json").read_text())
    return {
        "scenario": "A fourth reorder candidate appears after a governed forecast update",
        "source": "historical_DataHub_integration_record_not_a_new_live_DataHub_run",
        "evidence": [
            {"id": "E1", "label": "Historical capture provenance", "value": {
                "verified_at": proof["verified_at"], "context_source": proof["context_source"],
                "datahub_version": proof["datahub_version"], "fictional_business": "Fiction Retail"}},
            {"id": "E2", "label": "Governed analytics change", "value": proof["analytics"]},
            {"id": "E3", "label": "Recorded approval and supersession lifecycle", "value": proof["lifecycle"]},
            {"id": "E4", "label": "Historical DataHub write-back verification", "value": {
                "status": proof["projection_status"], "document_urn": proof["datahub_document_urn"],
                "read_back_verified": proof["read_back_verified"]}},
            {"id": "E5", "label": "Evidence context", "value": proof["context_facts"]},
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.env_file:
        # Read only the approved variable. Never print the file or its contents.
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
    packet = (packet_from_comparison(json.loads(args.comparison.read_text()))
              if args.comparison else historical_packet())
    try:
        result = review_packet(packet)
    except ReviewUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "model": result["model"],
                      "input_sha256": result["input_sha256"], "usage": result["usage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
