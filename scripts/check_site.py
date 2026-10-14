#!/usr/bin/env python3
"""Check that the committed static website can be deployed without EdgeInstant-Eval."""

import json
from pathlib import Path
import sys
from urllib.parse import urlparse


def check_site(site):
    site = Path(site).resolve()
    required = (
        "index.html", "app.js", "styles.css", "lib/data.js",
        "assets/favicon.svg", ".nojekyll", "data/dashboard.json",
    )
    for relative in required:
        if not (site / relative).is_file():
            raise ValueError(f"Missing website asset: {relative}")

    manifest = json.loads((site / "data/dashboard.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or not manifest.get("rows"):
        raise ValueError("The included report snapshot is empty or has an unsupported schema")
    if {source["id"] for source in manifest["sources"]} != {"greedy", "sample128"}:
        raise ValueError("The website expects both greedy and sample128 report snapshots")

    breakdown_count = 0
    for run, benchmarks in manifest["breakdownFiles"].items():
        for benchmark, relative in benchmarks.items():
            parsed = urlparse(relative)
            if parsed.scheme or parsed.netloc or relative.startswith("/"):
                raise ValueError(f"Breakdown URL must work under a project subpath: {relative}")
            path = (site / relative).resolve()
            if not path.is_relative_to(site) or not path.is_file():
                raise ValueError(f"Missing breakdown asset: {relative}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("run") != run or payload.get("benchmark") != benchmark:
                raise ValueError(f"Breakdown metadata does not match its manifest entry: {relative}")
            breakdown_count += 1

    files = [path for path in site.rglob("*") if path.is_file()]
    size = sum(path.stat().st_size for path in files)
    print(f"Website ready: {len(manifest['rows']):,} observations, "
          f"{breakdown_count} breakdown files, {size / 1024 / 1024:.1f} MiB.")
    print("Uses the included snapshot; the evaluation checkout is not needed to publish.")


if __name__ == "__main__":
    try:
        check_site(Path(__file__).resolve().parents[1] / "site")
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.exit(f"Website check failed: {error}")
