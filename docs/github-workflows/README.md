# CI and Pages workflows

These workflow files are staged here because the GitHub token used to push this
release does not have the `workflow` scope. GitHub rejects any push that creates
or updates `.github/workflows/*` without that scope.

To activate them:

1. Create a fine-grained or classic token with the **workflow** scope (and
   `repo` for a classic token).
2. Copy the files into place:
   ```bash
   mkdir -p .github/workflows
   cp docs/github-workflows/ci.yml .github/workflows/
   cp docs/github-workflows/pages.yml .github/workflows/
   git add .github/workflows
   git commit -m "ci: enable tests and Pages"
   git push
   ```
3. In **Settings → Pages**, choose **GitHub Actions** as the source (or use the
   `gh-pages` branch that ships with the landing page).

The workflows are intentionally not active until that token exists.
