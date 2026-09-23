# PR Target Validation

Validates a pull request target branch against the release label on the Linear issue referenced by its head branch.

- A Linear label named `X.Y.Z` or `release:X.Y.Z` requires `release/vX.Y.Z` by default.
- No release label requires `dev` by default.

To manually validate a pull request, enable dry-run mode and provide its URL. The action reads the PR head and base branches from GitHub, then runs the same Linear validation:

```yaml
- name: Dry-run PR target validation
  uses: caido/action-pr-target@<commit-sha>
  with:
    dry-run: true
    pr-url: https://github.com/caido/action-pr-target/pull/123
    linear-access-key: ${{ secrets.LINEAR_ISSUES_ACCESS_KEY }}
```

The workflow's `GITHUB_TOKEN` is used to read PR details by default. If the PR is in a repository that token cannot access, pass a suitable read-only token with `github-token`.

```yaml
- name: Validate PR target
  uses: caido/action-pr-target@<commit-sha>
  with:
    branch: ${{ github.event.pull_request.head.ref }}
    target: ${{ github.event.pull_request.base.ref }}
    linear-access-key: ${{ secrets.LINEAR_ISSUES_ACCESS_KEY }}
```

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `branch` | no | | PR head branch containing the Linear issue identifier. Required unless `dry-run` is enabled. |
| `target` | no | | PR base branch to validate. Required unless `dry-run` is enabled. |
| `linear-access-key` | yes | | Linear API key used to retrieve issue labels. |
| `teams` | no | `ENG,MAN,SUP` | Allowed Linear team prefixes. |
| `default-target` | no | `dev` | Target required when no release label exists. |
| `release-prefix` | no | `release/v` | Prefix prepended to the release label version. |
| `dry-run` | no | `false` | Resolve the PR branches from `pr-url` and validate them. |
| `pr-url` | no | | GitHub PR URL to validate when `dry-run` is enabled. |
| `github-token` | no | workflow `GITHUB_TOKEN` | Token used to read the PR details in dry-run mode. |
