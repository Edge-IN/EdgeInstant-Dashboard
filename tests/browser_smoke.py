#!/usr/bin/env python3
"""Check a served dashboard, including a GitHub Pages subdirectory URL.

Requires the optional Playwright Python package and its Chromium browser.
Example: python tests/browser_smoke.py --url http://127.0.0.1:8765
"""

import argparse
import csv
import io
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def run(url: str, artifact_dir: Path) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checks, errors, failed_requests, breakdown_requests = [], [], [], []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(request.url))
        page.on("request", lambda request: breakdown_requests.append(request.url) if "/breakdowns/" in request.url else None)
        page.goto(url, wait_until="networkidle")
        expect(page.locator("table.matrix")).to_be_visible()
        data = page.request.get(url.rstrip("/") + "/data/dashboard.json").json()
        sources = {(r["run"], r["model_id"], r["benchmark"], r["metric"], r["k"]): r for r in data["rows"]}

        def reset():
            page.goto(url, wait_until="networkidle")
            expect(page.locator("#page-title")).to_have_text("Greedy")

        def model_ids():
            return page.locator("table.matrix tbody tr").evaluate_all("rows => rows.map(row => row.dataset.modelRow)")

        def selected_models():
            return page.locator('.model-chip[aria-pressed="true"]').evaluate_all("chips => chips.map(chip => chip.dataset.model)")

        def columns():
            return page.locator("table.matrix [data-sort-benchmark]").evaluate_all("buttons => buttons.map(button => [button.dataset.sortBenchmark, button.dataset.sortMetric])")

        def check_matrix(run_id="greedy", k=1):
            actual = page.locator("table.matrix tbody tr").evaluate_all("""rows => rows.map(row => ({
                model: row.dataset.modelRow,
                cells: [...row.querySelectorAll('td')].map(cell => cell.textContent.trim())
            }))""")
            cols = columns()
            assert actual and cols
            for row in actual:
                assert len(row["cells"]) == len(cols), row
                for (bench, metric), text in zip(cols, row["cells"]):
                    source = sources.get((run_id, row["model"], bench, metric, k))
                    if source is None or source["pass_at_k"] is None:
                        assert text == "—", (row["model"], bench, metric, text)
                    else:
                        assert abs(float(text) - source["pass_at_k"] * 100) <= 0.051, (source, text)

        def export_rows():
            with page.expect_download() as download_info:
                page.locator("#export").click()
            download = download_info.value
            return list(csv.DictReader(io.StringIO(Path(download.path()).read_text(encoding="utf-8-sig"))))

        def check_export(run_id, ids, bench_metrics, budgets):
            exported = export_rows()
            expected = {key for key in sources if key[0] == run_id and key[1] in ids and (key[2], key[3]) in bench_metrics and key[4] in budgets}
            actual = {(r["run"], r["model_id"], r["benchmark"], r["metric"], int(r["k"])) for r in exported}
            assert actual == expected, {"missing": list(expected - actual), "unexpected": list(actual - expected)}
            assert len(exported) == len(expected), "Duplicate CSV rows"
            for row in exported:
                key = (row["run"], row["model_id"], row["benchmark"], row["metric"], int(row["k"]))
                assert float(row["pass_at_k"]) == sources[key]["pass_at_k"]

        expect(page.locator("#page-title")).to_have_text("Greedy")
        expect(page.locator("#navigation [data-run]")).to_have_count(2)
        assert set(page.locator("#navigation [data-run]").evaluate_all("els => els.map(el => el.dataset.run)")) == {"greedy", "sample128"}
        assert "Times New Roman" in page.locator("#page-title").evaluate("el => getComputedStyle(el).fontFamily")
        assert "Times New Roman" in page.locator(".selection-label").first.evaluate("el => getComputedStyle(el).fontFamily")
        body = page.locator("body").inner_text().lower()
        for removed in ("from evidence to insight", "compare capabilities", "understand the trade-offs", "about these results", "methodology", "the value of another try", "more samples, more possibility"):
            assert removed not in body, removed
        assert len(columns()) == len(data["benchmarks"])
        expected_models = {r["model_id"] for r in data["rows"] + data["coverage"] if r["run"] == "greedy"}
        assert set(selected_models()) == expected_models == set(model_ids())
        check_matrix()
        assert not breakdown_requests, "Breakdown assets must load only when opening details"
        page.screenshot(path=str(artifact_dir / "greedy-desktop.png"), full_page=True)
        checks.append("Greedy opens directly with the full source-accurate matrix, two run tabs, Times New Roman headings, and no slogans or methodology")

        cell = page.locator("table.matrix .score-cell[data-detail]").first
        model_id = cell.get_attribute("data-detail")
        bench = cell.get_attribute("data-detail-benchmark")
        metric = cell.get_attribute("data-detail-metric")
        source = sources[("greedy", model_id, bench, metric, 1)]
        cell.click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        expect(page.locator("#detail-content")).to_contain_text(source["evaluation_id"])
        expect(page.locator("#breakdown-content .loading")).to_have_count(0)
        assert breakdown_requests, "Result details did not request their subject breakdowns"
        page.keyboard.press("Escape")
        expect(page.locator("#detail-dialog")).not_to_be_visible()
        checks.append("Matrix cells open the matching evaluation and lazy subject breakdowns; Escape closes details")

        page.locator('[data-models="none"]').click()
        assert not model_ids() and not selected_models()
        page.locator("#export").click()
        expect(page.locator("#toast")).to_have_text("No results selected.")
        empty_url = page.url
        page.reload(wait_until="networkidle")
        assert not model_ids() and not selected_models() and page.url == empty_url
        ids = ["edgeinstant-v2m_formal", "qwen3.5-2b"]
        for model_id in ids:
            page.locator(f'.model-chip[data-model="{model_id}"]').click()
        assert set(model_ids()) == set(ids)
        page.locator('[data-benches="none"]').click()
        assert not columns()
        page.reload(wait_until="networkidle")
        assert not columns()
        page.locator("#export").click()
        expect(page.locator("#toast")).to_have_text("No results selected.")
        for bench in ("ai2d", "hallusionbench"):
            page.locator(f'.benchmark-chip[data-benchmark="{bench}"]').click()
        assert set(map(tuple, columns())) == {("ai2d", "accuracy"), ("hallusionbench", "Avg")}
        check_matrix()
        check_export("greedy", set(ids), set(map(tuple, columns())), {1})
        page.locator("#metric-mode").select_option("all")
        assert len(columns()) == 5
        check_matrix()
        check_export("greedy", set(ids), set(map(tuple, columns())), {1})
        alternate = page.locator('table.matrix .score-cell[data-detail-benchmark="hallusionbench"][data-detail-metric="qAcc"]').first
        alternate.click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        expect(page.locator("#detail-content")).to_contain_text("Question accuracy")
        expect(page.locator("#breakdown-content .loading")).to_have_count(0)
        page.keyboard.press("Escape")
        saved_url = page.url
        page.reload(wait_until="networkidle")
        assert page.url == saved_url and set(model_ids()) == set(ids) and len(columns()) == 5
        check_matrix()
        checks.append("Model and benchmark chips, all/none, alternate metrics, filtered CSV, and nonempty/empty URL selections persist correctly")

        reset()
        page.keyboard.press("/")
        expect(page.locator("#model-search")).to_be_focused()
        page.locator("#model-search").fill("impossible-model-name-9487")
        assert not model_ids()
        expect(page.locator("#model-search")).to_be_focused()
        page.locator("#model-search").fill("qwen3.5")
        assert model_ids() and all("qwen3.5" in model_id for model_id in model_ids())
        page.locator("#model-search").fill("")
        page.locator("#family-select").select_option("EdgeInstant")
        families = {m["id"]: m["family"] for m in data["models"]}
        assert model_ids() and all(families[model_id] == "EdgeInstant" for model_id in model_ids())
        page.locator("#category-select").select_option("instruction")
        assert columns() == [["ifeval", "prompt_strict"]]
        check_matrix()
        check_export("greedy", set(model_ids()), {("ifeval", "prompt_strict")}, {1})
        checks.append("Search, slash shortcut, family and suite filters restrict the actual matrix and exported rows")

        reset()
        sort_bench, sort_metric = "ai2d", "accuracy"
        sort_button = page.locator(f'[data-sort-benchmark="{sort_bench}"][data-sort-metric="{sort_metric}"]')
        previous = None
        for _ in range(2):
            sort_button.click()
            values = [sources.get(("greedy", model_id, sort_bench, sort_metric, 1), {}).get("pass_at_k") for model_id in model_ids()]
            numeric = [v for v in values if v is not None]
            assert numeric == sorted(numeric) or numeric == sorted(numeric, reverse=True), values
            assert values[:len(numeric)] == numeric, "Missing values must sort after numeric values"
            if previous is not None:
                assert numeric == previous[::-1], (numeric, previous)
            previous = numeric
        check_matrix()
        checks.append("Benchmark headings sort numerically in both directions, with missing scores last")

        page.locator('#navigation [data-run="sample128"]').click()
        expect(page.locator("#page-title")).to_have_text("Sample")
        expect(page.locator("#k-select")).to_be_visible()
        page.locator("#k-select").select_option("128")
        check_matrix("sample128", 128)
        page.locator('[data-models="none"]').click()
        for model_id in ids:
            page.locator(f'.model-chip[data-model="{model_id}"]').click()
        page.locator('[data-benches="none"]').click()
        page.locator('.benchmark-chip[data-benchmark="hallusionbench"]').click()
        page.locator("#metric-mode").select_option("all")
        check_matrix("sample128", 128)
        check_export("sample128", set(ids), set(map(tuple, columns())), {128})
        page.reload(wait_until="networkidle")
        expect(page.locator("#k-select")).to_have_value("128")
        check_matrix("sample128", 128)
        checks.append("Sample matrix faithfully displays selected k, models and metrics; CSV and reload retain the same selection")

        page.locator('[data-mode="curves"]').click()
        page.locator(".benchmark-select").select_option("hallusionbench")
        page.locator(".metric-select").select_option("qAcc")
        points = page.locator(".chart-point")
        assert points.count() == len(ids) * 8
        points.first.focus()
        expect(page.locator("#chart-tooltip")).to_be_visible()
        expect(page.locator("#chart-tooltip")).to_contain_text("k = 1")
        check_export("sample128", set(ids), {("hallusionbench", "qAcc")}, {1, 2, 4, 8, 16, 32, 64, 128})
        page.locator('[data-models="all"]').click()
        displayed_ids = set(points.evaluate_all("els => els.map(el => el.dataset.point)"))
        expected_ids = {r["model_id"] for r in data["rows"] if r["run"] == "sample128" and r["benchmark"] == "hallusionbench" and r["metric"] == "qAcc" and r["pass_at_k"] is not None}
        assert displayed_ids == expected_ids and len(displayed_ids) > 6
        page.screenshot(path=str(artifact_dir / "sample-curves-desktop.png"), full_page=True)
        page.reload(wait_until="networkidle")
        expect(page.locator(".metric-select")).to_have_value("qAcc")
        assert page.locator(".chart-point").count() > 6 * 8
        checks.append("Sampling curves show every selected model without a six-model limit, keyboard tooltips, alternate metrics and exact all-budget CSV")

        reset()
        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.screenshot(path=str(artifact_dir / "greedy-dark.png"), full_page=True)
        checks.append("Dark theme persists after reload")

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        phone = mobile.new_page()
        phone.on("pageerror", lambda error: errors.append(str(error)))
        phone.on("requestfailed", lambda request: failed_requests.append(request.url))
        phone.goto(url, wait_until="networkidle")
        expect(phone.locator("#page-title")).to_have_text("Greedy")
        assert not phone.evaluate("document.documentElement.scrollWidth > window.innerWidth"), "Mobile page overflows horizontally"
        phone.screenshot(path=str(artifact_dir / "greedy-mobile.png"), full_page=True)
        phone.locator("#theme-toggle").click()
        expect(phone.locator("html")).to_have_attribute("data-theme", "dark")
        phone.locator("#theme-toggle").click()
        expect(phone.locator("html")).to_have_attribute("data-theme", "light")
        phone.locator("table.matrix .score-cell[data-detail]").first.click()
        expect(phone.locator("#detail-dialog")).to_be_visible()
        assert phone.locator("#detail-dialog").bounding_box()["width"] <= 390
        expect(phone.locator("#breakdown-content .loading")).to_have_count(0)
        phone.locator("[data-close]").click()
        phone.locator('#navigation [data-run="sample128"]').click()
        phone.locator('[data-mode="curves"]').click()
        expect(phone.locator(".curve-svg")).to_be_visible()
        assert not phone.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        phone.screenshot(path=str(artifact_dir / "sample-curves-mobile.png"), full_page=True)
        mobile_axis_size = phone.locator(".curve-svg text").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize) * el.getScreenCTM().a")
        assert mobile_axis_size >= 8, f"Mobile sampling axis font is too small: {mobile_axis_size}px"
        checks.append("390px mobile navigation, theme, table and details fit the viewport; sampling chart labels remain readable")
        mobile.close()

        assert not errors, f"Browser errors: {errors}"
        assert not failed_requests, f"Failed network requests: {failed_requests}"
        checks.append("No JavaScript errors or failed network requests")
        context.close()
        browser.close()

    report = {"url": url, "checks": checks, "javascript_errors": errors, "failed_requests": failed_requests}
    (artifact_dir / "browser-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    run(args.url, args.artifacts)
