#!/usr/bin/env python3
"""Build dashboard assets from EdgeInstant-Eval CSV reports (Python stdlib only).

Never reads summary.json or question_diagnostics.csv. Breakdowns are streamed to
separate benchmark files. Every input is validated before publishing; content
addressed breakdown files are committed first and dashboard.json atomically last.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "reports.config.json"
INTEGER_FIELDS = {
    "k", "n_questions", "n_units", "n_samples", "samples_per_question_min",
    "samples_per_question_max", "generated_tokens",
}
FLOAT_FIELDS = {
    "pass_at_k", "ci_lower", "ci_upper", "chance_at_k", "score",
    "invalid_answer_rate", "truncation_rate", "mean_answer_diversity",
    "mean_answer_entropy_nats", "raw_score", "score_max", "score_percent",
}
BREAKDOWN_FIELDS = (
    "model_id", "metric", "k", "pass_at_k", "ci_lower", "ci_upper",
    "chance_at_k", "aggregation", "n_questions", "n_units", "score",
    "group_by", "group", "raw_score", "score_max", "score_percent",
)
BENCHMARKS = {
    "ai2d": ("AI2D", "vision"),
    "cmmlu_0shot": ("CMMLU · 0-shot", "text"),
    "cmmlu_5shot": ("CMMLU · 5-shot", "text"),
    "gpqa_diamond": ("GPQA Diamond", "text"),
    "gpqa_main": ("GPQA Main", "text"),
    "hallusionbench": ("HallusionBench", "vision"),
    "ifeval": ("IFEval", "instruction"),
    "mathvision": ("MathVision", "vision"),
    "mathvista_mini": ("MathVista Mini", "vision"),
    "mmbench_cn_v11": ("MMBench CN v1.1", "vision"),
    "mmbench_en_v11": ("MMBench EN v1.1", "vision"),
    "mmlu_pro": ("MMLU-Pro", "text"),
    "mmlu_redux": ("MMLU-Redux", "text"),
    "mmmu": ("MMMU", "vision"),
    "mmstar": ("MMStar", "vision"),
    "ocrbench": ("OCRBench", "vision"),
    "realworldqa": ("RealWorldQA", "vision"),
    "supergpqa": ("SuperGPQA", "text"),
}
PRIMARY_METRICS = {
    "ifeval": "prompt_strict", "hallusionbench": "Avg", "ocrbench": "score",
    "mmbench_cn_v11": "circular_accuracy", "mmbench_en_v11": "circular_accuracy",
}
INPUT_FILES = (
    "summary.csv", "coverage_gaps.csv", "excluded.csv", "selected.csv",
    "execution.csv", "breakdowns.csv",
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ImportFailure(ValueError):
    """An actionable report/configuration validation failure."""


def json_dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def finite_tree(value, location):
    if isinstance(value, float) and not math.isfinite(value):
        raise ImportFailure(f"{location}: non-finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            finite_tree(item, f"{location}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            finite_tree(item, f"{location}[{i}]")


def read_json(value, location):
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ImportFailure(f"{location}: invalid JSON: {exc}") from exc
    finite_tree(result, location)
    return result


def typed_row(row, location):
    result = {}
    for field, value in row.items():
        if field is None or value is None:
            raise ImportFailure(f"{location}: malformed CSV row")
        if field in INTEGER_FIELDS | FLOAT_FIELDS:
            if not value.strip():
                result[field] = None
                continue
            try:
                result[field] = int(value) if field in INTEGER_FIELDS else float(value)
            except ValueError as exc:
                raise ImportFailure(f"{location}: invalid number for {field}: {value!r}") from exc
            if not math.isfinite(result[field]):
                raise ImportFailure(f"{location}: non-finite number for {field}")
        else:
            result[field] = value
    return result


def csv_rows(path, run, required, *, allow_empty=False):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            # Eval writes a blank CSV when an optional audit report has no rows.
            # Reject nonempty content after a blank first line as malformed.
            if allow_empty and not headers and not any(reader.reader):
                return
            if len(headers) != len(set(headers)):
                raise ImportFailure(f"{path}: duplicate CSV headers")
            missing = set(required) - set(headers)
            if missing:
                raise ImportFailure(f"{path}: missing columns: {', '.join(sorted(missing))}")
            for line, raw in enumerate(reader, 2):
                location = f"{path}:{line}"
                row = typed_row(raw, location)
                if row.get("setting_id") != run["settingId"]:
                    raise ImportFailure(
                        f"{location}: setting_id {row.get('setting_id')!r} does not match "
                        f"run {run['id']!r} ({run['settingId']!r})"
                    )
                for field in required:
                    if field not in FLOAT_FIELDS and (row.get(field) is None or row.get(field) == ""):
                        raise ImportFailure(f"{location}: missing value for {field}")
                for field in ("benchmark", "model_id"):
                    if field in row and not IDENTIFIER.fullmatch(row[field]):
                        raise ImportFailure(f"{location}: invalid {field} {row[field]!r}")
                if "k" in row and (row["k"] is None or row["k"] < 1):
                    raise ImportFailure(f"{location}: k must be a positive integer")
                row["run"] = run["id"]
                yield row
    except (OSError, csv.Error) as exc:
        raise ImportFailure(f"Cannot read {path}: {exc}") from exc


def family(model_id):
    lowered = model_id.lower()
    for prefix, label in (("edgeinstant", "EdgeInstant"), ("qwen", "Qwen"), ("minicpm", "MiniCPM")):
        if lowered.startswith(prefix):
            return label
    return "Other"


def compact_execution(row):
    result = {key: val for key, val in row.items() if key not in ("telemetry", "full_run_estimate")}
    for field in ("telemetry", "full_run_estimate"):
        raw = row.get(field)
        if not raw:
            result[field] = None
            continue
        parsed = read_json(raw, f"execution {row.get('evaluation_id')} {field}")
        if not isinstance(parsed, dict):
            raise ImportFailure(f"execution {field} must be a JSON object")
        compact = {key: val for key, val in parsed.items() if not isinstance(val, (dict, list))}
        if field == "telemetry":
            preflight = parsed.get("preflight") or {}
            if not isinstance(preflight, dict):
                raise ImportFailure("execution telemetry.preflight must be an object")
            compact["backend"] = preflight.get("backend")
            compact["backend_version"] = preflight.get("backend_version")
            compact["dtype"] = preflight.get("dtype")
            hardware = preflight.get("hardware") or {}
            gpu_ids = parsed.get("generation_gpu_ids") or []
            if not isinstance(hardware, dict) or not isinstance(gpu_ids, list):
                raise ImportFailure("execution hardware must be an object and GPU ids must be an array")
            compact["gpu_name"] = preflight.get("gpu_name") or hardware.get("gpu_name")
            compact["generation_gpu_count"] = len(gpu_ids)
        result[field] = compact
    return result


def load_config(config_path, eval_root_override=None, output_override=None):
    config_path = Path(config_path).resolve()
    try:
        config = read_json(config_path.read_text(encoding="utf-8"), str(config_path))
    except OSError as exc:
        raise ImportFailure(f"Cannot read configuration {config_path}: {exc}") from exc
    if not isinstance(config, dict) or not isinstance(config.get("runs"), list) or not config["runs"]:
        raise ImportFailure("Configuration must contain a non-empty runs array")
    eval_root = Path(eval_root_override).resolve() if eval_root_override else (
        config_path.parent / config.get("evalRoot", "../EdgeInstant-Eval")).resolve()
    output = Path(output_override).resolve() if output_override else (
        config_path.parent / config.get("output", "site/data")).resolve()
    # No output placement inside the evaluation repository, ever.
    if output == eval_root or eval_root in output.parents:
        raise ImportFailure("Output must be outside the evaluation repository")
    runs, ids = [], set()
    for spec in config["runs"]:
        if not isinstance(spec, dict):
            raise ImportFailure("Every run must be an object")
        run_id = spec.get("id", "")
        if not isinstance(run_id, str) or not IDENTIFIER.fullmatch(run_id):
            raise ImportFailure(f"Invalid run id: {run_id!r}")
        if run_id in ids:
            raise ImportFailure(f"Duplicate run id: {run_id}")
        ids.add(run_id)
        if not isinstance(spec.get("path"), str) or not spec["path"]:
            raise ImportFailure(f"Run {run_id}: path is required")
        report_path = (eval_root / spec["path"]).resolve()
        if output == report_path or report_path in output.parents:
            raise ImportFailure("Output must be outside all source report directories")
        analysis_path = report_path / "analysis"
        if not analysis_path.is_dir():
            raise ImportFailure(f"Run {run_id}: missing analysis directory {analysis_path}")
        params = spec.get("parameters")
        if not isinstance(params, dict):
            raise ImportFailure(f"Run {run_id}: parameters object is required")
        n = params.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ImportFailure(f"Run {run_id}: parameters.n must be a positive integer")
        for key in ("temperature", "seed"):
            if key not in params or isinstance(params[key], bool) or not isinstance(params[key], (int, float)):
                raise ImportFailure(f"Run {run_id}: numeric parameters.{key} is required")
        label = spec.get("label", run_id)
        if not isinstance(label, str) or not label.strip():
            raise ImportFailure(f"Run {run_id}: label must be a non-empty string")
        runs.append({
            "id": run_id, "label": label, "settingId": spec.get("settingId", report_path.name),
            "parameters": params, "path": analysis_path, "sourcePath": spec["path"],
        })
    return runs, output


def unique_rows(path, run, required, key_fields, *, allow_empty=False):
    seen = set()
    result = []
    for row in csv_rows(path, run, required, allow_empty=allow_empty):
        key = tuple(row.get(field) for field in key_fields)
        if key in seen:
            raise ImportFailure(f"{path}: duplicate key {key!r}")
        seen.add(key)
        result.append(row)
    return result


def stream_breakdowns(path, run, staging, summary_evaluations):
    """At most one CSV row is retained, apart from duplicate-detection keys."""
    handles, temp_paths, seen, counts = {}, {}, set(), {}
    try:
        required = ("setting_id", "model_id", "benchmark", "metric", "k", "group_by", "group", "evaluation_id")
        for row in csv_rows(path, run, required):
            key = tuple(row[field] for field in ("model_id", "benchmark", "metric", "k", "group_by", "group"))
            if key in seen:
                raise ImportFailure(f"{path}: duplicate breakdown key {key!r}")
            seen.add(key)
            if key[:4] not in summary_evaluations:
                raise ImportFailure(f"{path}: breakdown has no summary row: {key[:4]!r}")
            if row["evaluation_id"] != summary_evaluations[key[:4]]:
                raise ImportFailure(f"{path}: breakdown evaluation_id differs from summary for {key[:4]!r}")
            benchmark = row["benchmark"]
            if benchmark not in handles:
                target = staging / "breakdowns" / run["id"] / f"{benchmark}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = target.open("w", encoding="utf-8")
                prefix = {"schemaVersion": 1, "run": run["id"], "benchmark": benchmark}
                stream.write(json_dump(prefix)[:-1] + ',"rows":[')
                handles[benchmark] = stream
                temp_paths[benchmark] = target
                counts[benchmark] = 0
            if counts[benchmark]:
                handles[benchmark].write(",")
            compact = {field: row.get(field) for field in BREAKDOWN_FIELDS}
            handles[benchmark].write(json_dump(compact))
            counts[benchmark] += 1
        for stream in handles.values():
            stream.write("]}\n")
    finally:
        for stream in handles.values():
            stream.close()
    files = {}
    for benchmark, path in sorted(temp_paths.items()):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        named = path.with_name(f"{benchmark}-{digest.hexdigest()[:12]}.json")
        path.rename(named)
        files[benchmark] = "data/" + named.relative_to(staging).as_posix()
    return files, sum(counts.values())


def build(config_path=DEFAULT_CONFIG, eval_root=None, output=None):
    runs, output = load_config(config_path, eval_root, output)
    # Raise before creating staging files if any declared input is unavailable.
    source_snapshot = {}
    for run in runs:
        for filename in INPUT_FILES:
            path = run["path"] / filename
            if not path.is_file():
                raise ImportFailure(f"Run {run['id']}: missing {path}")
            stat = path.stat()
            source_snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sources": [], "models": [], "benchmarks": [], "rows": [], "coverage": [],
        "excluded": [], "selected": [], "execution": [], "breakdownFiles": {},
    }
    model_names, benchmark_metrics = {}, {}
    with tempfile.TemporaryDirectory(prefix=".edgeinstant-import-", dir=output.parent) as temp_dir:
        staging = Path(temp_dir)
        for run in runs:
            root = run["path"]
            required = ("setting_id", "model_id", "benchmark", "metric", "k", "evaluation_id")
            key_fields = ("model_id", "benchmark", "metric", "k")
            rows = unique_rows(root / "summary.csv", run, (*required, "pass_at_k"), key_fields)
            if not rows:
                raise ImportFailure(f"{root / 'summary.csv'}: no result rows")
            summary_evaluations = {tuple(row[field] for field in key_fields): row["evaluation_id"] for row in rows}
            run_metrics = {}
            for row in rows:
                run_metrics.setdefault(row["benchmark"], set()).add(row["metric"])
                if row["k"] > run["parameters"]["n"]:
                    raise ImportFailure(f"{root / 'summary.csv'}: k exceeds configured n for {row['model_id']}")
                for count_field in ("samples_per_question_min", "samples_per_question_max"):
                    if row.get(count_field) is not None and row[count_field] != run["parameters"]["n"]:
                        raise ImportFailure(
                            f"{root / 'summary.csv'}: {count_field} does not match configured n "
                            f"for {row['model_id']}"
                        )
                model_names.setdefault(row["model_id"], row.get("model_name") or row["model_id"])
                benchmark_metrics.setdefault(row["benchmark"], set()).add(row["metric"])
            for benchmark, metrics in run_metrics.items():
                expected = PRIMARY_METRICS.get(benchmark, "accuracy")
                if benchmark in BENCHMARKS and expected not in metrics:
                    raise ImportFailure(
                        f"Run {run['id']}, benchmark {benchmark}: expected primary metric {expected!r} is missing"
                    )
            payload["rows"].extend(rows)
            for filename, target, extra, keys in (
                ("coverage_gaps.csv", "coverage", ("reason",), ("model_id", "benchmark", "reason")),
                ("excluded.csv", "excluded", ("evaluation_id", "reason"), ("evaluation_id", "benchmark", "reason")),
                ("selected.csv", "selected", ("evaluation_id",), ("model_id", "benchmark")),
            ):
                metadata = unique_rows(
                    root / filename, run, ("setting_id", "model_id", "benchmark", *extra), keys,
                    allow_empty=target in {"coverage", "excluded"},
                )
                payload[target].extend(metadata)
                if target == "selected":
                    selection = {(row["model_id"], row["benchmark"]): row["evaluation_id"] for row in metadata}
                    summary_pairs = {(row["model_id"], row["benchmark"]) for row in rows}
                    if set(selection) != summary_pairs:
                        raise ImportFailure(f"{root}: selected/summary model-benchmark coverage differs")
                    for result in rows:
                        pair = (result["model_id"], result["benchmark"])
                        if result["evaluation_id"] != selection[pair]:
                            raise ImportFailure(f"{root}: selected/summary evaluation_id differs for {pair!r}")
                # Audit metadata can reference prepared or excluded evaluations.
                # Only summary rows establish entries in the model catalog.
            execution = unique_rows(root / "execution.csv", run, ("setting_id", "evaluation_id", "model_id"),
                                    ("evaluation_id",))
            payload["execution"].extend(compact_execution(row) for row in execution)
            files, breakdown_count = stream_breakdowns(root / "breakdowns.csv", run, staging, summary_evaluations)
            payload["breakdownFiles"][run["id"]] = files
            updated = max((root / filename).stat().st_mtime for filename in INPUT_FILES)
            payload["sources"].append({
                "id": run["id"], "label": run["label"], "settingId": run["settingId"],
                "parameters": run["parameters"], "path": run["sourcePath"],
                "updatedAt": datetime.fromtimestamp(updated, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "rowCount": len(rows), "breakdownRowCount": breakdown_count,
                "selectedCount": sum(row["run"] == run["id"] for row in payload["selected"]),
            })
        payload["models"] = [
            {"id": model_id, "name": name, "family": family(model_id)}
            for model_id, name in sorted(model_names.items())
        ]
        for benchmark, metrics in sorted(benchmark_metrics.items()):
            name, category = BENCHMARKS.get(benchmark, (benchmark, "text"))
            primary = PRIMARY_METRICS.get(benchmark, "accuracy")
            if primary not in metrics:
                if benchmark in BENCHMARKS:
                    raise ImportFailure(f"Benchmark {benchmark}: expected primary metric {primary!r} is missing")
                primary = sorted(metrics)[0]
            payload["benchmarks"].append({
                "id": benchmark, "name": name, "category": category,
                "primaryMetric": primary, "metrics": sorted(metrics),
            })
        # Stable ordering makes diffs useful when updating a report.
        for field in ("rows", "coverage", "excluded", "selected", "execution"):
            payload[field].sort(key=lambda row: (
                row["run"], row.get("model_id", ""), row.get("benchmark", ""),
                row.get("metric", ""), row.get("k") or 0, row.get("evaluation_id", ""),
                row.get("reason", ""),
            ))
        for path, expected in source_snapshot.items():
            stat = path.stat()
            if (stat.st_mtime_ns, stat.st_size) != expected:
                raise ImportFailure(f"Source changed during import: {path}. Wait for report generation to finish and retry.")
        (staging / "dashboard.json").write_text(json_dump(payload) + "\n", encoding="utf-8")
        output.mkdir(parents=True, exist_ok=True)
        for path in sorted((staging / "breakdowns").rglob("*.json")) if (staging / "breakdowns").exists() else []:
            destination = output / path.relative_to(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)
        os.replace(staging / "dashboard.json", output / "dashboard.json")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Report configuration JSON")
    parser.add_argument("--eval-root", type=Path, help="Override the evaluation repository root")
    parser.add_argument("--output", type=Path, help="Override output directory (default: site/data)")
    args = parser.parse_args(argv)
    try:
        data = build(args.config, args.eval_root, args.output)
    except (ImportFailure, OSError) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    print(f"Imported {len(data['rows']):,} results, {len(data['models'])} models, "
          f"{len(data['benchmarks'])} benchmarks from {len(data['sources'])} runs.")
    for source in data["sources"]:
        print(f"  {source['id']}: {source['rowCount']:,} results; "
              f"{source['breakdownRowCount']:,} breakdown rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())

