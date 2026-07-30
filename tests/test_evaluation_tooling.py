import json
import unittest

from tests.evaluation.evaluate import (
    DEFAULT_CASES,
    DEFAULT_POLICIES,
    build_report,
    load_json,
    load_jsonl,
    validate_annotations,
    validate_arbitrations,
    validate_cases,
    validate_manifest,
    validate_results,
)


class EvaluationDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_jsonl(DEFAULT_CASES)
        cls.policy_document = load_json(DEFAULT_POLICIES)
        cls.policies = cls.policy_document["policies"]

    def test_public_dataset_is_complete_and_valid(self):
        self.assertEqual(validate_cases(self.cases, self.policy_document), [])
        self.assertEqual(len(self.cases), 50)
        self.assertEqual(len({case["case_id"] for case in self.cases}), 50)

    def test_complete_perfect_run_passes_all_gates(self):
        results = []
        annotations = []
        for case in self.cases:
            evidence = []
            rank = 1
            for expected in case["expected_evidence"]:
                for page in expected["pages"]:
                    evidence.append(
                        {
                            "document_id": expected["document_id"],
                            "page": page,
                            "rank": rank,
                        }
                    )
                    rank += 1
            results.append(
                {
                    "case_id": case["case_id"],
                    "actual_behavior": case["expected_behavior"],
                    "retrieved_evidence": evidence[:5],
                    "latency_ms": 1000,
                    "trace_id": f"trace-{case['case_id']}",
                }
            )

            dimensions = set(self.policies[case["scoring_policy"]]["dimensions"])
            judgments = {
                metric: "pass" if metric in dimensions else "na"
                for metric in ("answer", "citation", "refusal", "grading")
            }
            annotations.append(
                {
                    "case_id": case["case_id"],
                    "annotator_id": "first",
                    "judgments": judgments,
                    "notes": "",
                }
            )
            if case["critical"]:
                annotations.append(
                    {
                        "case_id": case["case_id"],
                        "annotator_id": "second",
                        "judgments": judgments,
                        "notes": "",
                    }
                )

        valid_ids = {case["case_id"] for case in self.cases}
        self.assertEqual(validate_results(results, valid_ids), [])
        self.assertEqual(validate_annotations(annotations, valid_ids), [])

        manifest = {
            "run_id": "unit-test",
            "code_commit": "test-commit",
            "material_commit": "test-material",
            "models": {},
            "prompt_versions": {},
            "retrieval_parameters": {},
        }
        report, defects = build_report(
            self.cases,
            self.policy_document,
            results,
            annotations,
            manifest,
        )
        self.assertIn("状态：`PASS`", report)
        self.assertIn("100.0%", report)
        self.assertEqual(defects, [])

    def test_empty_run_is_incomplete_and_creates_reproducible_defects(self):
        manifest = {
            "run_id": "empty-test",
            "code_commit": "test-commit",
            "material_commit": "test-material",
            "models": {},
            "prompt_versions": {},
            "retrieval_parameters": {},
        }
        report, defects = build_report(
            self.cases,
            self.policy_document,
            [],
            [],
            manifest,
        )
        self.assertIn("状态：`INCOMPLETE`", report)
        self.assertGreaterEqual(len(defects), 50)
        self.assertTrue(all(defect["reproduction_steps"] for defect in defects))

    def test_arbitration_resolves_a_disagreement_and_records_failure(self):
        case = dict(next(case for case in self.cases if case["case_id"] == "db-001"))
        case["critical"] = True
        results = [
            {
                "case_id": case["case_id"],
                "actual_behavior": case["expected_behavior"],
                "retrieved_evidence": [
                    {
                        "document_id": expected["document_id"],
                        "page": page,
                        "rank": rank,
                    }
                    for expected in case["expected_evidence"]
                    for rank, page in enumerate(expected["pages"], start=1)
                ],
                "latency_ms": 1000,
                "trace_id": "trace-arbitration",
            }
        ]
        annotations = [
            {
                "case_id": case["case_id"],
                "annotator_id": "B",
                "judgments": {
                    "answer": "pass",
                    "citation": "pass",
                    "refusal": "na",
                    "grading": "na",
                },
                "notes": "",
            },
            {
                "case_id": case["case_id"],
                "annotator_id": "E",
                "judgments": {
                    "answer": "fail",
                    "citation": "pass",
                    "refusal": "na",
                    "grading": "na",
                },
                "notes": "",
            },
        ]
        arbitrations = [
            {
                "case_id": case["case_id"],
                "metric": "answer",
                "arbiter_id": "A",
                "judgment": "fail",
                "reason": "Evidence does not support the answer.",
            }
        ]
        manifest = {
            "run_id": "arbitration-test",
            "code_commit": "test-commit",
            "material_commit": "test-material",
            "models": {},
            "prompt_versions": {},
            "retrieval_parameters": {},
        }

        report, defects = build_report(
            [case],
            self.policy_document,
            results,
            annotations,
            manifest,
            arbitrations,
        )

        self.assertIn("状态：`FAIL`", report)
        self.assertIn("已仲裁标注分歧：1 条", report)
        self.assertFalse(any(defect["metric"] == "annotation" for defect in defects))
        self.assertTrue(
            any(defect["metric"] == "answer_accuracy" for defect in defects)
        )

    def test_templates_are_valid_json_or_jsonl(self):
        template_dir = DEFAULT_CASES.parent / "templates"
        manifest = json.loads(
            (template_dir / "run-manifest.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(
            len(load_jsonl(template_dir / "run-results.example.jsonl")),
            1,
        )
        self.assertEqual(
            len(load_jsonl(template_dir / "annotations.example.jsonl")),
            2,
        )
        arbitrations = load_jsonl(template_dir / "arbitrations.example.jsonl")
        self.assertEqual(len(arbitrations), 1)
        self.assertEqual(
            validate_arbitrations(arbitrations, {"db-001"}),
            [],
        )
        for schema_path in DEFAULT_CASES.parent.glob("*.schema.json"):
            with self.subTest(schema=schema_path.name):
                json.loads(schema_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
