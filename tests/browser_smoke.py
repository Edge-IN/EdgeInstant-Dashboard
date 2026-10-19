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

        def check_model_chips(run_id):
            expected = {row["model_id"] for row in data["rows"] if row["run"] == run_id}
            actual = set(page.locator(".model-chip").evaluate_all(
                "chips => chips.map(chip => chip.dataset.model)"
            ))
            metadata_only = {
                row["model_id"] for row in data["coverage"] + data["excluded"]
                if row["run"] == run_id
            } - expected
            assert not actual & metadata_only, f"Metadata-only models shown: {actual & metadata_only}"
            assert actual == expected, {"missing": expected - actual, "unexpected": actual - expected}
            return expected

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

        low_color, middle_color, high_color = "rgb(215, 48, 39)", "rgb(255, 255, 191)", "rgb(26, 152, 80)"
        sample_colors = {}

        def rgb(color):
            return [int(channel.strip()) for channel in color.removeprefix("rgb(").removesuffix(")").split(",")]

        def check_column_colors(target):
            actual = target.locator("table.matrix tbody tr").evaluate_all("""rows => rows.map(row => ({
                model: row.dataset.modelRow,
                colors: [...row.querySelectorAll('td')].map(cell => getComputedStyle(cell).backgroundColor)
            }))""")
            cols = target.locator("table.matrix [data-sort-benchmark]").evaluate_all(
                "buttons => buttons.map(button => [button.dataset.sortBenchmark, button.dataset.sortMetric])"
            )
            for index, (bench, metric) in enumerate(cols):
                values = [
                    (sources[("greedy", row["model"], bench, metric, 1)]["pass_at_k"], row["colors"][index])
                    for row in actual
                    if sources.get(("greedy", row["model"], bench, metric, 1), {}).get("pass_at_k") is not None
                ]
                if not values:
                    continue
                low, high = min(score for score, _ in values), max(score for score, _ in values)
                for score, color in values:
                    if low == high:
                        assert color == middle_color, (bench, metric, score, color)
                    elif score == low:
                        assert color == low_color, (bench, metric, score, color)
                    elif score == high:
                        assert color == high_color, (bench, metric, score, color)

        def check_table_styles(target, selector="table.matrix"):
            cells = target.locator(f"{selector} th, {selector} td")
            assert cells.count(), f"No table cells in {selector}"
            assert cells.evaluate_all("""cells => cells.every(cell => {
                const style = getComputedStyle(cell);
                return style.textAlign === 'center' && style.verticalAlign === 'middle';
            })"""), "Table headers and values must be centered"
            colored = target.locator(f"{selector} td.score-heat")
            assert colored.count(), "Numeric scores need heatmap colors"
            values = colored.evaluate_all("""cells => cells.map(cell => {
                const button = cell.querySelector('.score-cell');
                return {
                    color: getComputedStyle(cell).backgroundColor,
                    value: parseFloat(cell.textContent),
                    key: button ? [button.dataset.detail, button.dataset.detailBenchmark,
                        button.dataset.detailMetric, button.dataset.detailK].join('|') : null,
                    centered: !button || getComputedStyle(button).textAlign === 'center'
                };
            })""")
            for value in values:
                assert value["centered"]
                assert value["color"] not in ("transparent", "rgba(0, 0, 0, 0)")
                if selector == "table.matrix" and target.locator("#page-title").inner_text() == "Sample":
                    key = value["key"]
                    assert sample_colors.setdefault(key, value["color"]) == value["color"], "Sample colors must retain their fixed percentage scale"
                if selector != "table.matrix" or target.locator("#page-title").inner_text() != "Greedy":
                    red, green, _ = rgb(value["color"])
                    if value["value"] <= 25:
                        assert red > green, value
                    elif value["value"] >= 75:
                        assert green > red, value
            neutral = target.locator(f"{selector} td:has(.missing)")
            assert neutral.evaluate_all("cells => cells.every(cell => !cell.classList.contains('score-heat'))"), "Missing values must not receive score colors"
            if selector == "table.matrix" and target.locator("#page-title").inner_text() == "Greedy":
                check_column_colors(target)
            return values

        def check_square_plot(target):
            dimensions = target.locator(".curve-svg").evaluate("""svg => {
                const grids = [...svg.querySelectorAll('.curve-grid')].filter(line =>
                    line.y1.baseVal.value === line.y2.baseVal.value &&
                    line.x1.baseVal.value !== line.x2.baseVal.value);
                const first = grids[0], ys = grids.map(line => line.y1.baseVal.value);
                const matrix = svg.getScreenCTM();
                return {
                    width: Math.abs(first.x2.baseVal.value - first.x1.baseVal.value) * Math.hypot(matrix.a, matrix.b),
                    height: (Math.max(...ys) - Math.min(...ys)) * Math.hypot(matrix.c, matrix.d)
                };
            }""")
            assert dimensions["width"] > 200, dimensions
            assert abs(dimensions["width"] - dimensions["height"]) <= 1, dimensions

        def check_curve_table():
            bench = page.locator(".benchmark-select").input_value()
            metric = page.locator(".metric-select").input_value()
            actual = page.locator("table.curve-table tbody tr").evaluate_all("""rows => rows.map(row => ({
                model: row.dataset.modelRow,
                cells: [...row.querySelectorAll('td')].map(cell => cell.textContent.trim())
            }))""")
            budgets = [1, 2, 4, 8, 16, 32, 64, 128]
            expect(page.locator("table.curve-table thead th")).to_have_count(9)
            assert actual
            for row in actual:
                assert len(row["cells"]) == len(budgets)
                for k, text in zip(budgets, row["cells"]):
                    source = sources.get(("sample128", row["model"], bench, metric, k))
                    if source is None or source["pass_at_k"] is None:
                        assert text == "—"
                    else:
                        assert abs(float(text) - source["pass_at_k"] * 100) <= 0.051, (source, text)
            assert page.locator(".curve-panel").evaluate(
                "panel => !!(panel.compareDocumentPosition(document.querySelector('.curve-table')) & Node.DOCUMENT_POSITION_FOLLOWING)"
            ), "Sampling table must follow its plot"
            check_table_styles(page)
            check_square_plot(page)

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
        expected_models = check_model_chips("greedy")
        assert set(selected_models()) == expected_models == set(model_ids())
        check_matrix()
        heatmap = check_table_styles(page)
        assert len({cell["color"] for cell in heatmap}) > 5, "Scores need a range of heatmap colors"
        expect(page.locator(".score-scale")).to_contain_text("per column")
        checks.append("Centered Greedy tables scale every visible benchmark column independently from red to green, with neutral missing cells")
        assert not breakdown_requests, "Breakdown assets must load only when opening details"
        page.screenshot(path=str(artifact_dir / "greedy-desktop.png"), full_page=True)
        checks.append("Greedy opens directly with the full source-accurate matrix, two run tabs, Times New Roman headings, and no slogans or methodology")

        # Route a small fixture only in an isolated browser context, keeping the
        # actual imported data checks above and below unchanged.
        fixture_ids = sorted(expected_models)[:4]
        fixture = dict(data)
        fixture["rows"] = []
        fixture_values = {
            ("ai2d", "accuracy"): [0, .1, .2, None],
            ("hallusionbench", "Avg"): [.7, .8, .9, None],
            ("hallusionbench", "qAcc"): [.4, .4, .4, None],
            ("hallusionbench", "aAcc"): [None] * 4,
            ("hallusionbench", "fAcc"): [None] * 4,
        }
        for (bench, metric), values in fixture_values.items():
            for model_id, value in zip(fixture_ids, values):
                fixture["rows"].append({
                    "run": "greedy", "model_id": model_id, "benchmark": bench,
                    "metric": metric, "k": 1, "pass_at_k": value,
                })
        fixture_context = browser.new_context()
        fixture_context.route("**/data/dashboard.json", lambda route: route.fulfill(json=fixture))
        fixture_page = fixture_context.new_page()
        fixture_page.goto(url.rstrip("/") + "/#run=greedy&models=" + ",".join(fixture_ids)
                          + "&benches=ai2d,hallusionbench&metrics=all", wait_until="networkidle")
        expect(fixture_page.locator("table.matrix")).to_be_visible()

        def fixture_cell(model_id, bench, metric):
            return fixture_page.locator(
                f'.score-cell[data-detail="{model_id}"][data-detail-benchmark="{bench}"][data-detail-metric="{metric}"]'
            ).locator("..")

        def cell_color(cell):
            return cell.evaluate("cell => getComputedStyle(cell).backgroundColor")

        for bench, metric in (("ai2d", "accuracy"), ("hallusionbench", "Avg")):
            assert [cell_color(fixture_cell(model_id, bench, metric)) for model_id in fixture_ids[:3]] == [low_color, middle_color, high_color]
        assert fixture_cell(fixture_ids[0], "ai2d", "accuracy").inner_text().strip() == "0.0"
        assert fixture_page.locator("table.matrix td:has(.missing)").count() == 11
        assert fixture_page.locator("table.matrix td:has(.missing)").evaluate_all(
            "cells => cells.every(cell => !cell.classList.contains('score-heat'))"
        )
        for model_id in fixture_ids[:3]:
            assert cell_color(fixture_cell(model_id, "hallusionbench", "qAcc")) == middle_color
        fixture_page.locator(f'.model-chip[data-model="{fixture_ids[0]}"]').click()
        for bench, metric in (("ai2d", "accuracy"), ("hallusionbench", "Avg")):
            assert cell_color(fixture_cell(fixture_ids[1], bench, metric)) == low_color
            assert cell_color(fixture_cell(fixture_ids[2], bench, metric)) == high_color
        fixture_page.locator(f'.model-chip[data-model="{fixture_ids[2]}"]').click()
        assert fixture_page.locator("table.matrix td.score-heat").count() == 3
        assert fixture_page.locator("table.matrix td.score-heat").evaluate_all(
            "(cells, neutral) => cells.every(cell => getComputedStyle(cell).backgroundColor === neutral)", middle_color
        )
        fixture_context.close()
        checks.append("Independent column scales handle zero, disjoint score ranges, equal values, missing columns and model-selection changes")

        summary_ids = {row["model_id"] for row in data["rows"]}
        stale_ids = sorted({
            row["model_id"] for row in data["coverage"] + data["excluded"]
        } - summary_ids)
        if stale_ids:
            retained_id = min(expected_models)
            page.goto(url.rstrip("/") + "/#run=greedy&models=" + ",".join([retained_id, *stale_ids]),
                      wait_until="networkidle")
            check_model_chips("greedy")
            assert set(selected_models()) == {retained_id}
            assert set(model_ids()) == {retained_id}
            check_matrix()
            page.reload(wait_until="networkidle")
            assert set(selected_models()) == {retained_id}
            checks.append("Shared URLs with metadata-only models retain valid selections and never display phantom models")
            reset()

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
        check_table_styles(page, "#breakdown-table table")
        assert page.locator("#breakdown-table td:nth-child(3)").evaluate_all(
            "cells => cells.every(cell => !cell.classList.contains('score-heat'))"
        ), "Unit counts must not use the percentage heatmap"
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
        check_table_styles(page)
        check_export("greedy", set(ids), set(map(tuple, columns())), {1})
        page.locator("#metric-mode").select_option("all")
        assert len(columns()) == 5
        check_matrix()
        check_table_styles(page)
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
        check_table_styles(page)
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
        check_model_chips("sample128")
        checks.append("Model chips include only summary results for their run; coverage-only and excluded-only models stay hidden")
        expect(page.locator(".curve-svg")).to_be_visible()
        expect(page.locator(".curve-table")).to_be_attached()
        expect(page.locator("[data-mode]")).to_have_count(0)
        expect(page.locator("#metric-mode")).to_have_count(0)
        check_curve_table()
        expect(page.locator("#k-select")).to_be_visible()
        page.locator("#k-select").select_option("128")
        check_curve_table()
        page.locator('[data-models="none"]').click()
        page.locator("#export").click()
        expect(page.locator("#toast")).to_have_text("No results selected.")
        for model_id in ids:
            page.locator(f'.model-chip[data-model="{model_id}"]').click()
        page.locator('[data-benches="none"]').click()
        expect(page.locator(".curve-svg")).to_have_count(0)
        page.locator('.benchmark-chip[data-benchmark="hallusionbench"]').click()
        page.locator(".benchmark-select").select_option("hallusionbench")
        page.locator(".metric-select").select_option("qAcc")
        check_curve_table()
        check_export("sample128", set(ids), {("hallusionbench", "qAcc")}, {1, 2, 4, 8, 16, 32, 64, 128})
        page.reload(wait_until="networkidle")
        expect(page.locator("#k-select")).to_have_value("128")
        expect(page.locator(".metric-select")).to_have_value("qAcc")
        check_curve_table()
        page.goto(page.url + "&mode=table", wait_until="networkidle")
        expect(page.locator(".curve-svg")).to_be_visible()
        expect(page.locator("[data-mode]")).to_have_count(0)
        check_curve_table()
        checks.append("Sample opens a square pass@k plot above its source-accurate eight-budget table, including legacy table URLs and exact filtered CSV")

        points = page.locator(".chart-point")
        assert points.count() == len(ids) * 8
        points.first.scroll_into_view_if_needed()
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        points.first.focus()
        expect(page.locator("#chart-tooltip")).to_be_visible()
        expect(page.locator("#chart-tooltip")).to_contain_text("k = 1")
        check_export("sample128", set(ids), {("hallusionbench", "qAcc")}, {1, 2, 4, 8, 16, 32, 64, 128})
        page.locator('[data-models="all"]').click()
        displayed_ids = set(points.evaluate_all("els => els.map(el => el.dataset.point)"))
        expected_ids = {r["model_id"] for r in data["rows"] if r["run"] == "sample128" and r["benchmark"] == "hallusionbench" and r["metric"] == "qAcc" and r["pass_at_k"] is not None}
        assert displayed_ids == expected_ids and len(displayed_ids) > 6
        check_curve_table()
        sample_cell = page.locator('.curve-table .score-cell[data-detail-k="128"]').first
        sample_id = sample_cell.get_attribute("data-detail")
        sample_cell.click()
        expect(page.locator("#detail-dialog")).to_be_visible()
        expect(page.locator("#detail-content")).to_contain_text(sources[("sample128", sample_id, "hallusionbench", "qAcc", 128)]["evaluation_id"])
        expect(page.locator("#detail-content .badge")).to_contain_text("k = 128")
        expect(page.locator("#breakdown-content .loading")).to_have_count(0)
        check_table_styles(page, "#breakdown-table table")
        page.keyboard.press("Escape")
        page.evaluate("window.scrollTo(0, 0); document.activeElement?.blur()")
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
        check_table_styles(page)
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
        expect(phone.locator(".curve-svg")).to_be_visible()
        expect(phone.locator(".curve-table")).to_be_attached()
        expect(phone.locator("[data-mode]")).to_have_count(0)
        check_square_plot(phone)
        check_table_styles(phone)
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
