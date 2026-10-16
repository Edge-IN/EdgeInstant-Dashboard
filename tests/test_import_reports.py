"""Behavioral coverage for the report-to-static-data boundary."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "import_reports.py"
spec = importlib.util.spec_from_file_location("import_reports", MODULE_PATH)
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ImportReportsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.eval_root = self.root / "eval"
        self.analysis = self.eval_root / "reports" / "setting-a" / "analysis"
        self.analysis.mkdir(parents=True)
        self.config = self.root / "reports.config.json"
        self.output = self.root / "site" / "data"
        self.config_data = {
            "evalRoot": "eval", "output": "site/data",
            "runs": [{"id": "greedy", "label": "Greedy", "path": "reports/setting-a",
                      "parameters": {"n": 1, "temperature": 0.0, "seed": 20260929}}],
        }
        self.write_config()
        self.summary = {
            "model_id": "edgeinstant-small", "model_name": "EdgeInstant Small",
            "benchmark": "ocrbench", "metric": "score", "k": "1",
            "pass_at_k": "0.72", "ci_lower": "", "ci_upper": "",
            "chance_at_k": "", "score": "720", "raw_score": "720",
            "score_max": "1000", "score_percent": "72",
            "generated_tokens": "0", "invalid_answer_rate": "0",
            "n_questions": "1000", "n_units": "1000", "n_samples": "1000",
            "evaluation_id": "setting-a/edgeinstant-small/vision/2026-10-01/0001",
            "setting_id": "setting-a", "date": "2026-10-01",
            "protocol_group": "cohort-1", "scope": "benchmark",
        }
        self.write_csv("summary.csv", [self.summary])
        self.selected = {
            key: self.summary[key] for key in (
                "model_id", "model_name", "benchmark", "evaluation_id", "setting_id",
                "date", "n_questions", "scope", "protocol_group",
            )
        }
        self.write_csv("selected.csv", [self.selected])
        self.write_csv("coverage_gaps.csv", [], ["setting_id", "model_id", "benchmark", "reason"])
        self.write_csv("excluded.csv", [], [
            "evaluation_id", "model_id", "benchmark", "date", "setting_id", "reason", "status",
        ])
        self.execution = {
            **{key: self.summary[key] for key in ("model_id", "benchmark", "evaluation_id", "setting_id", "date")},
            "telemetry": json.dumps({
                "total_generated_tokens": 0, "peak_memory_bytes": 0,
                "generation_gpu_ids": ["0", "1"],
                "preflight": {"backend": "vllm", "hardware": {"gpu_name": "test GPU"},
                              "probe_outputs": [{"text": "DO NOT SHIP"}]},
            }),
            "full_run_estimate": json.dumps({
                "gpu_hours_at_observed_rate": 0, "qualification": "generation only",
                "timing_groups": {"vision": {"gpu_seconds": 1}},
            }),
        }
        self.write_csv("execution.csv", [self.execution])
        self.breakdown = {**self.summary, "group_by": "category", "group": "document"}
        self.write_csv("breakdowns.csv", [self.breakdown])

    def write_config(self):
        self.config.write_text(json.dumps(self.config_data), encoding="utf-8")

    def write_csv(self, filename, rows, fields=None, directory=None):
        fields = fields or list(rows[0])
        with ((directory or self.analysis) / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def build(self):
        return importer.build(self.config)

    def test_numeric_blanks_zero_ocr_raw_and_provenance(self):
        data = self.build()
        row = data["rows"][0]
        self.assertEqual(row["run"], "greedy")
        self.assertEqual(row["pass_at_k"], 0.72)
        self.assertEqual(row["raw_score"], 720.0)
        self.assertEqual(row["score_max"], 1000.0)
        self.assertIsNone(row["ci_lower"])
        self.assertEqual(row["invalid_answer_rate"], 0)
        self.assertEqual(row["generated_tokens"], 0)
        self.assertIsInstance(row["k"], int)
        self.assertEqual(data["sources"][0]["parameters"]["seed"], 20260929)
        self.assertEqual(data["sources"][0]["settingId"], "setting-a")
        self.assertEqual(data["selected"][0]["evaluation_id"], row["evaluation_id"])
        self.assertEqual(data["benchmarks"][0]["primaryMetric"], "score")
        self.assertEqual(data["models"][0]["family"], "EdgeInstant")
        self.assertEqual(data["execution"][0]["telemetry"]["peak_memory_bytes"], 0)
        self.assertEqual(data["execution"][0]["telemetry"]["generation_gpu_count"], 2)
        self.assertEqual(data["execution"][0]["telemetry"]["gpu_name"], "test GPU")
        self.assertNotIn("preflight", data["execution"][0]["telemetry"])
        self.assertNotIn("timing_groups", data["execution"][0]["full_run_estimate"])

    def test_missing_score_is_null_not_zero(self):
        self.summary["pass_at_k"] = ""
        self.write_csv("summary.csv", [self.summary])
        data = self.build()
        self.assertIsNone(data["rows"][0]["pass_at_k"])

    def test_registry_uses_summary_models_and_preserves_metadata_only_models(self):
        coverage = [
            {"setting_id": "setting-a", "model_id": "coverage-only", "benchmark": "ocrbench",
             "reason": "No evaluation selected"},
            {"setting_id": "setting-a", "model_id": self.summary["model_id"], "benchmark": "ai2d",
             "reason": "Missing benchmark"},
        ]
        excluded = [
            {"setting_id": "setting-a", "model_id": "excluded-only", "benchmark": "ocrbench",
             "evaluation_id": "setting-a/excluded-only/vision/2026-09-01/0001",
             "reason": "Incomplete evaluation", "status": "incomplete"},
        ]
        self.write_csv("coverage_gaps.csv", coverage)
        self.write_csv("excluded.csv", excluded)
        for score, expected_score in (("0.72", 0.72), ("0", 0.0), ("", None)):
            with self.subTest(score=score):
                self.summary["pass_at_k"] = score
                self.write_csv("summary.csv", [self.summary])
                data = self.build()
                self.assertEqual(data["models"], [{
                    "id": self.summary["model_id"], "name": self.summary["model_name"],
                    "family": "EdgeInstant",
                }])
                self.assertEqual(data["rows"][0]["pass_at_k"], expected_score)
                self.assertCountEqual(data["coverage"], [{**row, "run": "greedy"} for row in coverage])
                self.assertEqual(data["excluded"], [{**row, "run": "greedy"} for row in excluded])

    def test_optional_audit_files_accept_header_only_or_empty_exports(self):
        # Eval emits a blank CSV when there are no coverage gaps or exclusions.
        initial = self.build()
        self.assertEqual(initial["coverage"], [])
        self.assertEqual(initial["excluded"], [])
        for coverage_contents in (b"", b"\n", b"\r\n\r\n"):
            for excluded_contents in (b"", b"\n", b"\r\n\r\n"):
                with self.subTest(coverage=coverage_contents, excluded=excluded_contents):
                    (self.analysis / "coverage_gaps.csv").write_bytes(coverage_contents)
                    (self.analysis / "excluded.csv").write_bytes(excluded_contents)
                    data = self.build()
                    self.assertEqual(data["coverage"], [])
                    self.assertEqual(data["excluded"], [])
                    self.assertEqual(data["rows"], initial["rows"])
                    self.assertEqual(data["selected"], initial["selected"])
                    self.assertEqual(data["execution"], initial["execution"])
                    self.assertEqual(data["breakdownFiles"], initial["breakdownFiles"])

    def test_nonempty_malformed_audit_files_preserve_published_snapshot(self):
        self.build()
        published = {
            path.relative_to(self.output): path.read_bytes()
            for path in self.output.rglob("*") if path.is_file()
        }
        malformed = (
            b"setting-a,edgeinstant-small,ocrbench,no gaps\n",
            b"\nsetting-a,edgeinstant-small,ocrbench,no gaps\n",
            b"setting_id,model_id,benchmark\nsetting-a,edgeinstant-small,ocrbench\n",
            b"setting_id,model_id,benchmark,reason,reason,evaluation_id\n",
            b" \t\n",
        )
        for filename in ("coverage_gaps.csv", "excluded.csv"):
            path = self.analysis / filename
            valid = path.read_bytes()
            for contents in malformed:
                with self.subTest(filename=filename, contents=contents):
                    path.write_bytes(contents)
                    try:
                        with self.assertRaises(importer.ImportFailure):
                            self.build()
                        self.assertEqual({
                            path.relative_to(self.output): path.read_bytes()
                            for path in self.output.rglob("*") if path.is_file()
                        }, published)
                    finally:
                        path.write_bytes(valid)

    def test_blank_required_files_preserve_published_snapshot(self):
        self.build()
        published = {
            path.relative_to(self.output): path.read_bytes()
            for path in self.output.rglob("*") if path.is_file()
        }
        for filename in ("summary.csv", "selected.csv", "execution.csv", "breakdowns.csv"):
            path = self.analysis / filename
            valid = path.read_bytes()
            for contents in (b"", b"\n", b"\r\n\r\n"):
                with self.subTest(filename=filename, contents=contents):
                    path.write_bytes(contents)
                    try:
                        with self.assertRaises(importer.ImportFailure):
                            self.build()
                        self.assertEqual({
                            path.relative_to(self.output): path.read_bytes()
                            for path in self.output.rglob("*") if path.is_file()
                        }, published)
                    finally:
                        path.write_bytes(valid)

    def test_breakdown_is_separate_and_content_addressed(self):
        data = self.build()
        url = data["breakdownFiles"]["greedy"]["ocrbench"]
        path = self.output.parent / url
        details = json.loads(path.read_text())
        self.assertEqual(details["run"], "greedy")
        self.assertEqual(details["benchmark"], "ocrbench")
        self.assertEqual(details["rows"][0]["group"], "document")
        self.assertEqual(details["rows"][0]["raw_score"], 720)
        self.assertIsNone(details["rows"][0]["ci_upper"])
        self.assertRegex(path.name, r"ocrbench-[0-9a-f]{12}\.json")
        repeated = self.build()
        self.assertEqual(data["breakdownFiles"], repeated["breakdownFiles"])

    def test_same_model_benchmark_in_different_sources_is_preserved(self):
        import shutil
        other = self.eval_root / "reports" / "setting-b" / "analysis"
        shutil.copytree(self.analysis, other)
        for path in other.glob("*.csv"):
            path.write_text(path.read_text().replace("setting-a", "setting-b"))
        self.config_data["runs"].append({
            "id": "sample128", "label": "Sample 128", "path": "reports/setting-b",
            "parameters": {"n": 128, "temperature": 1.0, "seed": 20260918},
        })
        self.write_config()
        data = self.build()
        self.assertEqual({row["run"] for row in data["rows"]}, {"greedy", "sample128"})
        self.assertEqual(len(data["rows"]), 2)
        self.assertEqual(data["sources"][1]["parameters"]["seed"], 20260918)

    def test_duplicate_summary_rejected_without_replacing_published_data(self):
        self.build()
        original = (self.output / "dashboard.json").read_bytes()
        self.write_csv("summary.csv", [self.summary, self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "duplicate key"):
            self.build()
        self.assertEqual((self.output / "dashboard.json").read_bytes(), original)

    def test_mismatched_setting_rejected(self):
        self.summary["setting_id"] = "wrong-run"
        self.write_csv("summary.csv", [self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "does not match run"):
            self.build()

    def test_non_finite_numeric_values_rejected(self):
        for value in ("nan", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.summary["pass_at_k"] = value
                self.write_csv("summary.csv", [self.summary])
                with self.assertRaisesRegex(importer.ImportFailure, "non-finite"):
                    self.build()

    def test_invalid_integer_and_missing_header_rejected(self):
        self.summary["k"] = "1.5"
        self.write_csv("summary.csv", [self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "invalid number for k"):
            self.build()
        del self.summary["k"]
        self.write_csv("summary.csv", [self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "missing columns: k"):
            self.build()

    def test_missing_input_and_output_inside_source_rejected(self):
        (self.analysis / "breakdowns.csv").unlink()
        with self.assertRaisesRegex(importer.ImportFailure, "missing .*breakdowns.csv"):
            self.build()
        with self.assertRaisesRegex(importer.ImportFailure, "outside the evaluation"):
            importer.build(self.config, output=self.eval_root / "data")

    def test_orphan_and_duplicate_breakdown_rejected(self):
        self.breakdown["k"] = "2"
        self.write_csv("breakdowns.csv", [self.breakdown])
        with self.assertRaisesRegex(importer.ImportFailure, "no summary row"):
            self.build()
        self.breakdown["k"] = "1"
        self.write_csv("breakdowns.csv", [self.breakdown, self.breakdown])
        with self.assertRaisesRegex(importer.ImportFailure, "duplicate breakdown"):
            self.build()

    def test_duplicate_run_ids_rejected(self):
        self.config_data["runs"].append(dict(self.config_data["runs"][0]))
        self.write_config()
        with self.assertRaisesRegex(importer.ImportFailure, "Duplicate run id"):
            self.build()

    def test_invalid_and_non_finite_execution_json_rejected(self):
        for value in ("{bad json", '{"peak_memory_bytes": NaN}', '[]'):
            with self.subTest(value=value):
                self.execution["telemetry"] = value
                self.write_csv("execution.csv", [self.execution])
                with self.assertRaises(importer.ImportFailure):
                    self.build()

    def test_large_diagnostic_files_are_never_opened(self):
        # Directories would raise if the importer accidentally tried to read them.
        (self.analysis / "summary.json").mkdir()
        (self.analysis / "question_diagnostics.csv").mkdir()
        self.assertEqual(len(self.build()["rows"]), 1)

    def test_family_does_not_guess_unknown_models(self):
        self.assertEqual(importer.family("s1_5_asr_tothemoon_sft_v3_clean_0917_v2"), "Other")
        self.assertEqual(importer.family("minicpm-o-4_5"), "MiniCPM")
        self.assertEqual(importer.family("qwen3.5-2b"), "Qwen")

    def test_selected_and_summary_evaluation_ids_must_agree(self):
        self.selected["evaluation_id"] = "setting-a/edgeinstant-small/vision/2026-09-01/0001"
        self.write_csv("selected.csv", [self.selected])
        with self.assertRaisesRegex(importer.ImportFailure, "selected/summary evaluation_id differs"):
            self.build()

    def test_selected_and_summary_coverage_must_agree(self):
        self.write_csv("selected.csv", [], list(self.selected))
        with self.assertRaisesRegex(importer.ImportFailure, "selected/summary model-benchmark coverage differs"):
            self.build()

    def test_breakdown_and_summary_evaluation_ids_must_agree(self):
        self.breakdown["evaluation_id"] = "setting-a/edgeinstant-small/vision/2026-09-01/0001"
        self.write_csv("breakdowns.csv", [self.breakdown])
        with self.assertRaisesRegex(importer.ImportFailure, "breakdown evaluation_id differs"):
            self.build()

    def test_changing_source_does_not_replace_published_snapshot(self):
        import os
        from unittest.mock import patch
        self.build()
        original = (self.output / "dashboard.json").read_bytes()
        stream = importer.stream_breakdowns
        def mutate_source(*args, **kwargs):
            result = stream(*args, **kwargs)
            source = self.analysis / "summary.csv"
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            return result
        with patch.object(importer, "stream_breakdowns", side_effect=mutate_source):
            with self.assertRaisesRegex(importer.ImportFailure, "Source changed during import"):
                self.build()
        self.assertEqual((self.output / "dashboard.json").read_bytes(), original)

    def test_missing_known_primary_metric_does_not_silently_switch(self):
        self.summary["metric"] = "accuracy"
        self.breakdown["metric"] = "accuracy"
        self.write_csv("summary.csv", [self.summary])
        self.write_csv("breakdowns.csv", [self.breakdown])
        with self.assertRaisesRegex(importer.ImportFailure, "expected primary metric 'score' is missing"):
            self.build()

    def test_sampling_metadata_must_match_configured_run(self):
        self.summary["k"] = "2"
        self.write_csv("summary.csv", [self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "k exceeds configured n"):
            self.build()
        self.summary["k"] = "1"
        self.summary["samples_per_question_max"] = "128"
        self.write_csv("summary.csv", [self.summary])
        with self.assertRaisesRegex(importer.ImportFailure, "samples_per_question_max does not match configured n"):
            self.build()

    def test_configuration_and_output_overrides(self):
        override = self.root / "override"
        importer.build(self.config, eval_root=self.eval_root, output=override)
        self.assertTrue((override / "dashboard.json").is_file())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()

