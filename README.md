# EdgeInstant Dashboard

A minimalist, interactive evaluation workspace for EdgeInstant-Eval. The included snapshot contains **28 evaluated models, 18 benchmarks, and 3,336 score observations** across the requested greedy and sample-128 reports. Greedy has 27 evaluated models and Sample has 15; the model sets differ.

The site uses native JavaScript, CSS, and SVG. Importing and serving require only **Python 3.10+**. There is no Node dependency, build step, database, CDN, or external font requirement.

**GitHub Pages:** **https://edge-in.github.io/EdgeInstant-Dashboard/**. The included workflow publishes `site/` on pushes to `main`. See [GITHUB_PAGES.md](GITHUB_PAGES.md) for upload and update commands.

## Run locally

From this directory:

```bash
python -m http.server 8765 --bind 127.0.0.1 --directory site
```

Open **http://localhost:8765**. Use HTTP rather than opening `index.html` directly; the dashboard fetches its JSON assets. `make serve` does the same thing. On a remote machine, forward port 8765 to your computer, for example `ssh -L 8765:127.0.0.1:8765 <your-host>`.

## Explore

- **Greedy:** a sortable score matrix. Select models and benchmarks with chips; filter by suite, family, or name. Switch between primary and all metrics. Click a score for source details and subject breakdowns.
- **Sample:** square pass@k curves with the corresponding table below, covering k = 1, 2, 4, 8, 16, 32, 64, and 128. Select models, a benchmark, and a metric. Chart points support hover and keyboard focus.

CSV export follows the displayed models, benchmarks, metrics, and sampling budgets. Shared URLs preserve selections and filters. Use `/` to focus model search and `Escape` to close result details. Light/dark appearance is stored locally. Wide result tables scroll within their panels on narrow screens.

## Refresh the data

After the evaluation reports have finished updating:

```bash
python scripts/import_reports.py
```

Reload the browser to see the new snapshot. The equivalent command is `make import`.

[reports.config.json](reports.config.json) specifies the evaluation repository and the two report directories. Paths in the config are resolved relative to the config file, so the default sibling layout works wherever these repositories are moved together:

```text
workspace/
  EdgeInstant-Eval/
  EdgeInstant-Dashboard/
```

The configured reports are:

- `greedy_n1_t0.0_p1.0_tk0_rp1.0_s20260929_mcq64_if4096_vis256_k1`
- `sample_n128_t1.0_p1.0_tk0_rp1.0_s20260918_mcq64_if4096_vis256_k1-2.4.8.16.32.64.128`

To point at a different evaluation checkout:

```bash
python scripts/import_reports.py --eval-root /path/to/EdgeInstant-Eval
```

For newer reports, change each run’s `path` and its decoding `parameters` in the config, then rerun the importer. Preserve the `greedy` and `sample128` IDs: the UI intentionally compares these two experiment types and budgets. New models and metrics are discovered automatically. For a new benchmark, extend `BENCHMARKS` and, if necessary, `PRIMARY_METRICS` in [scripts/import_reports.py](scripts/import_reports.py) to supply its display name, suite, and primary metric. Unknown benchmark IDs remain visible under the text suite until classified.

The importer also accepts `--config /path/to/config.json` and `--output /path/to/site/data`. The frontend expects the output directory to be named `data` beneath the served site root.

### Import behavior

The importer reads `analysis/summary.csv`, `selected.csv`, `excluded.csv`, `coverage_gaps.csv`, `execution.csv`, and `breakdowns.csv`. Coverage and exclusion reports may be blank when there are no entries. It streams the breakdowns and **does not read the multi-gigabyte summary JSON or question diagnostics**. It never writes to EdgeInstant-Eval.

Model selectors include only models with summary results in that run. Coverage gaps and excluded evaluations remain in the JSON as audit metadata; they do not add model choices. A model appears automatically after its results are imported.

Malformed numeric values, duplicate result keys, mismatched evaluation provenance, wrong sampling settings, missing primary metrics, and missing source files fail with an actionable error. The importer also rejects source files that change during the import. The previous `dashboard.json` stays intact on a failed import. Breakdown assets receive content-specific filenames and are written before the manifest is atomically replaced, keeping existing open views consistent during an update. Old breakdown assets remain available; for a clean deployment, import into a fresh `data` directory and deploy the complete site together.

The initial payload is approximately 5 MiB. Subject breakdown files are requested only when opening result details. The site retains previous breakdown assets for open views; run `make check-site` to see the current bundle size.

## Metric semantics

`pass_at_k` is the normalized score shown in charts and tables. The original raw score, score maximum, metric, aggregation, evaluation ID, scorer/parser versions, and prompt version remain available in result details or exported data.

- Sampled pass@1 estimates mean correctness across 128 temperature-1 completions. It is distinct from the one-completion greedy run.
- The two settings use different seeds. Differences are descriptive percentage-point changes; they are not paired significance tests.
- CMMLU is subject-macro averaged. MMBench uses circular accuracy. HallusionBench retains its grouped metrics. IFEval retains all four strict/loose prompt/instruction metrics. OCRBench retains its raw scale.
- The matrix selects HallusionBench `Avg`, IFEval `prompt_strict`, OCRBench `score`, and each other benchmark’s accuracy metric. There is no synthetic overall accuracy across these metrics.
- Reported confidence intervals are preserved. Missing intervals and missing results display as `—`; actual zero scores remain zero.
- Benchmark views can overlap. Counts across benchmarks, metrics, or sampling budgets must not be summed as unique questions or compute work.

## Validate

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

These tests exercise importer behavior, including zero/null handling, metric preservation, duplicate rejection, run provenance, lazy breakdowns, and safe failed updates. Browser interaction checks live separately in `tests/browser_smoke.py` and require an optional Playwright environment. With the local server running:

```bash
python -m venv .venv
.venv/bin/pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py --url http://127.0.0.1:8765
```

The smoke test checks real scores, navigation, filters, exports, subject details, chart interactions, URL restoration, theme persistence, and mobile layout. It saves screenshots and a check report in the ignored `artifacts/` directory.

## Deploy and maintain

For the prepared GitHub Pages workflow and exact upload/update commands, see [GITHUB_PAGES.md](GITHUB_PAGES.md). GitHub publishes the committed snapshot; it does not rerun the importer against the local evaluation repository.

Serve the **contents of `site/`** on any static HTTP host. Keep `index.html`, `app.js`, `styles.css`, `assets/`, `lib/`, and `data/` together. The app works below a URL subdirectory, uses hash URLs for shareable views, and needs no route fallback or application server. Serve `data/dashboard.json` with revalidation or a short cache lifetime when publishing frequent updates; content-specific breakdown files can be cached long-term.

```text
site/index.html       Page shell and metadata
site/styles.css       Responsive themes and layout
site/app.js           Views, charts, controls, exports, detail dialog
site/lib/data.js      Data selection, formatting, CSV helpers
site/data/            Generated report snapshot and breakdowns
scripts/              Python report importer
tests/                Importer tests and optional browser smoke tests
reports.config.json   Report locations and decoding settings
```
