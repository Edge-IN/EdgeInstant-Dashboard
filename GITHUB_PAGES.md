# Publish to GitHub Pages

Prepared destination: **https://edge-in.github.io/EdgeInstant-Dashboard/**

GitHub repository: **Edge-IN/EdgeInstant-Dashboard**

The workflow in [.github/workflows/pages.yml](.github/workflows/pages.yml) checks the importer and included data, then publishes **only `site/`**. It runs on pushes to `main` and can also be started manually. The source code, report import tools, and configuration stay in the repository; the website artifact contains the static application and its imported results.

The imported snapshot is included, so publishing does not need EdgeInstant-Eval, GPUs, Python packages, Node packages, or a build step. No upload or deployment has been performed during preparation.

## First upload to a new, empty repository

1. Sign in to GitHub and [create a public repository](https://github.com/new) named **EdgeInstant-Dashboard** under **Edge-IN**. Leave README, license, and .gitignore initialization unchecked; the local project already contains its files.
2. Run these commands in your `tmp` tmux window:

```bash
cd /default-filesys/workspace/czq/EdgeInstant-Dashboard
make check-site
git init -b main
git add .
git commit -m "Publish EdgeInstant evaluation dashboard"
git remote add origin https://github.com/Edge-IN/EdgeInstant-Dashboard.git
git push -u origin main
```

3. Open [repository Settings → Pages](https://github.com/Edge-IN/EdgeInstant-Dashboard/settings/pages). Under **Build and deployment**, select **GitHub Actions** as the source. Do not choose a branch folder: this workflow publishes `site/` as an artifact.
4. Open [Actions → Deploy dashboard to GitHub Pages](https://github.com/Edge-IN/EdgeInstant-Dashboard/actions/workflows/pages.yml), choose **Run workflow**, select **main**, and run it. This also handles the first push having started before Pages was enabled.
5. When the **Publish the dashboard** job succeeds, visit **https://edge-in.github.io/EdgeInstant-Dashboard/**. GitHub also shows the deployed URL on the workflow run and in Settings → Pages.

Use your configured GitHub credentials for the push. If you already use SSH authentication, the remote command can instead be:

```bash
git remote add origin git@github.com:Edge-IN/EdgeInstant-Dashboard.git
```

Choose one remote command, not both. If Git asks for a commit author, configure your own `user.name` and `user.email` before committing.

## If Edge-IN/EdgeInstant-Dashboard already contains commits

Use its existing history rather than initializing and pushing a separate history. For an existing repository with a `main` branch, clone it into a new sibling directory, copy the prepared project into that clone, and review the changes before committing:

```bash
cd /default-filesys/workspace/czq
git clone --branch main https://github.com/Edge-IN/EdgeInstant-Dashboard.git EdgeInstant-Dashboard-upload
rsync -av --exclude='.git/' --exclude='artifacts/' --exclude='.venv/' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  EdgeInstant-Dashboard/ EdgeInstant-Dashboard-upload/
cd EdgeInstant-Dashboard-upload
git diff --stat
git status --short
make check-site
git add .
git commit -m "Publish EdgeInstant evaluation dashboard"
git push -u origin main
```

These copy commands replace same-named project files in the new clone while retaining other files. Review any pre-existing Pages workflows so only the intended workflow publishes this project. If your publishing branch has another name, use that name in the clone command, push command, and the workflow’s `push.branches` setting.

Then enable **Settings → Pages → GitHub Actions** and run the workflow as above. No force push is needed.

## Publish updated evaluation results

Run this in the checkout connected to GitHub, after the upstream reports have finished updating:

```bash
make import
make check-site
git add site/data
git commit -m "Refresh evaluation results"
git push
```

The push starts the Pages workflow automatically. If the importer reports a source change in progress, wait for report generation to finish and rerun `make import`; it preserves the previous snapshot on failure.

For interface or configuration changes, commit those changed files too. The same workflow deploys them on the next push to `main`.

## Deployment details

- The application uses relative URLs, including module imports and breakdown files, so it works beneath `/EdgeInstant-Dashboard/` without a base-URL build setting.
- Shared views use URL hashes. Opening or refreshing them does not need a server routing fallback.
- `.nojekyll` marks the static bundle as ready to serve; no Jekyll configuration is needed.
- `make check-site` verifies that the committed snapshot and referenced breakdowns are available without the evaluation checkout.
- The deployment uses GitHub’s generated workflow token; no custom deployment secret is needed.
- The entire `site/data/` directory is part of the public website and its JSON and CSV exports.

The workflow and setup follow GitHub’s documentation for [custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [choosing GitHub Actions as the publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
