#!/usr/bin/env python3
"""Exercise a served dashboard and save desktop/mobile screenshots.

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
    checks = []
    errors = []
    failed_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(request.url))
        page.goto(url, wait_until="networkidle")
        expect(page.locator("#content .stat-card")).to_have_count(4)
        expect(page.locator("#page-title")).to_have_text("Evaluation overview")
        data = page.request.get(url.rstrip("/") + "/data/dashboard.json").json()
        assert len(data["models"]) > 0 and len(data["benchmarks"]) > 0
        assert page.locator(".bar-row").count() > 0
        page.screenshot(path=str(artifact_dir / "overview-desktop.png"), full_page=True)
        checks.append("Overview loads real report data and both chart types")
        page.locator(".curve-legend button").first.click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        expect(page.locator("#detail-content .badge")).to_contain_text("Sample ×128")
        expect(page.locator("#detail-content")).to_contain_text("sample_n128_")
        page.keyboard.press("Escape")
        checks.append("Overview curve legend opens sampled details even when the selected run is greedy")

        # A displayed score must match the imported source, including its normalization.
        page.locator('#navigation [data-view="benchmarks"]').click()
        row = page.locator("#content tbody tr").first
        model_id = row.locator("[data-detail]").get_attribute("data-detail")
        source = next(r for r in data["rows"] if r["run"] == "greedy" and r["benchmark"] == "ai2d" and r["model_id"] == model_id)
        expect(row.locator(".score-value")).to_have_text(f'{source["pass_at_k"] * 100:.1f}')
        displayed_ranks = [int(value) for value in page.locator("#content .rank").all_text_contents() if value != "—"]
        assert displayed_ranks == sorted(displayed_ranks), displayed_ranks
        scores_to_ranks = {}
        for item in page.locator("#content tbody tr").all():
            inspect = item.locator("[data-detail]")
            if not inspect.count():
                continue
            item_id = inspect.get_attribute("data-detail")
            source_row = next(r for r in data["rows"] if r["run"] == "greedy" and r["benchmark"] == "ai2d" and r["model_id"] == item_id)
            source_score, shown_rank = source_row["pass_at_k"], item.locator(".rank").inner_text()
            assert source_score not in scores_to_ranks or scores_to_ranks[source_score] == shown_rank
            scores_to_ranks[source_score] = shown_rank
        row.locator("[data-detail]").click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        expect(page.locator("#breakdown-content .loading")).to_have_count(0)
        expect(page.locator("#detail-content")).to_contain_text(source["evaluation_id"])
        page.keyboard.press("Escape")
        expect(page.locator("#detail-dialog")).not_to_be_visible()
        checks.append("Ranking score matches source; details load provenance and lazy breakdowns")
        checks.append("Tied scores share their rank and ranking positions never reverse")

        page.locator("#model-search").fill("impossible-model-name-9487")
        expect(page.locator("#content")).to_contain_text("No models match these filters")
        page.get_by_role("button", name="Clear filters", exact=True).click()
        page.locator("#family-select").select_option("EdgeInstant")
        assert page.locator("#content tbody tr").count() > 0
        for family in page.locator("#content tbody .model-sub").all_text_contents():
            assert family == "EdgeInstant", family
        page.locator("[data-reset]").first.click()
        page.keyboard.press("/")
        expect(page.locator("#model-search")).to_be_focused()
        page.locator("#model-search").fill("qwen3.5")
        assert page.locator("#content tbody tr").count() > 0
        expect(page.locator("#model-search")).to_be_focused()
        page.locator("[data-reset]").first.click()
        page.locator('[data-sort="score"]').click()
        scores = [float(text) for text in page.locator(".score-value").all_text_contents() if text != "—"]
        assert scores == sorted(scores), scores
        checks.append("Search, empty-state reset, family filter, keyboard shortcut and numeric sorting")

        page.locator('[data-run="sample128"]').click()
        expect(page.locator("#k-control")).to_be_visible()
        page.locator("#k-select").select_option("128")
        expect(page.locator("#content thead")).to_contain_text("Δ VS GREEDY")
        page.locator(".benchmark-select").select_option("hallusionbench")
        page.locator(".metric-select").select_option("qAcc")
        assert "metric=qAcc" in page.url and "k=128" in page.url
        saved_url = page.url
        page.reload(wait_until="networkidle")
        expect(page.locator(".metric-select")).to_have_value("qAcc")
        expect(page.locator("#k-select")).to_have_value("128")
        assert page.url == saved_url
        with page.expect_download() as download_info:
            page.locator("#export").click()
        download = download_info.value
        exported = list(csv.DictReader(io.StringIO(Path(download.path()).read_text(encoding="utf-8-sig"))))
        assert exported and all(r["run"] == "sample128" and r["metric"] == "qAcc" and r["k"] == "128" for r in exported)
        checks.append("Sample run, sampling budget, alternate metric, shareable URL restore and filtered CSV export")

        page.locator('[data-table="matrix"]').click()
        expect(page.locator("table.heatmap")).to_be_visible()
        page.locator(".heat-cell[data-detail]").first.click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        page.locator("[data-close]").click()
        page.locator("#category-select").select_option("instruction")
        expect(page.locator(".heatmap thead th")).to_have_count(2)
        page.locator("#category-select").select_option("all")
        checks.append("Matrix cells open correct result details and suite filter narrows benchmarks")

        page.locator('#navigation [data-view="sampling"]').click()
        page.locator(".benchmark-select").select_option("ai2d")
        points = page.locator(".chart-point")
        assert points.count() >= 8
        points.first.focus()
        expect(page.locator("#chart-tooltip")).to_be_visible()
        expect(page.locator("#chart-tooltip")).to_contain_text("k = 1")
        chip = page.locator(".model-chip.active").first
        chip_id = chip.get_attribute("data-toggle-pin")
        chip.click()
        expect(page.locator(f'.model-chip[data-toggle-pin="{chip_id}"]')).to_have_attribute("aria-pressed", "false")
        page.locator(f'.model-chip[data-toggle-pin="{chip_id}"]').click()
        page.screenshot(path=str(artifact_dir / "sampling-desktop.png"), full_page=True)
        checks.append("Sampling curves have keyboard tooltips and model selections update interactively")

        page.locator('#navigation [data-view="health"]').click()
        expect(page.locator("#content")).to_contain_text("Coverage gaps")
        expect(page.locator("#content")).to_contain_text("Report selection")
        page.locator('#navigation [data-view="methodology"]').click()
        expect(page.locator("#content")).to_contain_text("reports.config.json")
        expect(page.locator(".control-bar")).not_to_be_visible()
        checks.append("Run health and methodology views render with report provenance")

        page.goto(url, wait_until="networkidle")
        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.screenshot(path=str(artifact_dir / "overview-dark.png"), full_page=True)
        checks.append("Dark theme persists after reload")

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        phone = mobile.new_page()
        phone.on("pageerror", lambda error: errors.append(str(error)))
        phone.goto(url, wait_until="networkidle")
        expect(phone.locator("#page-title")).to_have_text("Evaluation overview")
        overflow = phone.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile page overflows horizontally"
        phone.screenshot(path=str(artifact_dir / "overview-mobile.png"), full_page=True)
        phone.locator("#mobile-theme").click()
        expect(phone.locator("html")).to_have_attribute("data-theme", "dark")
        phone.locator("#mobile-theme").click()
        expect(phone.locator("html")).to_have_attribute("data-theme", "light")
        phone.locator('#navigation [data-view="sampling"]').click()
        expect(phone.locator("#page-title")).to_have_text("The value of another try")
        assert not phone.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        phone.screenshot(path=str(artifact_dir / "sampling-mobile.png"), full_page=True)
        mobile_axis_size = phone.locator(".wide-chart .curve-svg text").first.evaluate("el => parseFloat(getComputedStyle(el).fontSize) * el.getScreenCTM().a")
        assert mobile_axis_size >= 8, f"Mobile sampling axis font is too small: {mobile_axis_size}px"
        phone.locator('#navigation [data-view="benchmarks"]').click()
        phone.locator("[data-detail]").first.click()
        expect(phone.locator("#detail-dialog")).to_be_visible()
        assert phone.locator("#detail-dialog").bounding_box()["width"] <= 390
        checks.append("390px mobile layout, navigation and result dialog work without page overflow")
        checks.append("Mobile theme toggle works and sampling chart labels remain readable")
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
