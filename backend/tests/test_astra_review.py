import json
import unittest
from unittest.mock import patch

from app.astra_review import ReviewUnavailable, canonical_hash, review_packet, validate_content


class AstraReviewTests(unittest.TestCase):
    def setUp(self):
        self.packet = {"evidence": [{"id": "E1", "value": "Candidate count changed from 3 to 4"}]}
        self.content = {"headline": "Review the additional candidate", "summary": "Evidence changed.",
                        "recommendation": "review_required", "findings": [{
                            "observation": "A candidate was added", "consequence": "Review the scope",
                            "evidence_ids": ["E1"]}], "next_steps": ["Review before approval"],
                        "limitations": ["Fixture data"]}

    def test_unknown_citation_rejected(self):
        self.content["findings"][0]["evidence_ids"] = ["invented"]
        with self.assertRaises(ReviewUnavailable):
            validate_content(json.dumps(self.content), self.packet)

    def test_model_cannot_return_approval(self):
        self.content["recommendation"] = "approved"
        with self.assertRaises(ReviewUnavailable):
            validate_content(json.dumps(self.content), self.packet)

    def test_empty_citations_rejected(self):
        self.content["findings"][0]["evidence_ids"] = []
        with self.assertRaises(ReviewUnavailable):
            validate_content(json.dumps(self.content), self.packet)

    def test_unknown_action_field_rejected(self):
        self.content["execute"] = "approve"
        with self.assertRaises(ReviewUnavailable):
            validate_content(json.dumps(self.content), self.packet)

    def test_hash_changes_when_evidence_changes(self):
        digest = canonical_hash(self.packet)
        self.packet["evidence"][0]["value"] = "Candidate count changed from 3 to 5"
        self.assertNotEqual(digest, canonical_hash(self.packet))

    def test_missing_key_has_no_network_fallback(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}), patch("app.astra_review.urlopen") as send:
            with self.assertRaises(ReviewUnavailable):
                review_packet(self.packet)
            send.assert_not_called()

    def test_valid_cited_review(self):
        self.assertEqual(validate_content(json.dumps(self.content), self.packet).recommendation,
                         "review_required")

    def test_malformed_evidence_rejected_before_network(self):
        for evidence in [[{}], [{"id": ""}], [{"id": "E1"}, {"id": "E1"}], "bad"]:
            with self.subTest(evidence=evidence), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("app.astra_review.urlopen") as send:
                with self.assertRaises(ReviewUnavailable):
                    review_packet({"evidence": evidence})
                send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
