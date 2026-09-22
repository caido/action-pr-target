# PR Target Validation

Validates a pull request target branch against the release label on the Linear issue referenced by its head branch.

- `release:X.Y.Z` requires `release/vX.Y.Z` by default.
- No release label requires `dev` by default.

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
| `branch` | yes | | PR head branch containing the Linear issue identifier. |
| `target` | yes | | PR base branch to validate. |
| `linear-access-key` | yes | | Linear API key used to retrieve issue labels. |
| `teams` | no | `ENG,MAN,SUP` | Allowed Linear team prefixes. |
| `default-target` | no | `dev` | Target required when no release label exists. |
| `release-prefix` | no | `release/v` | Prefix prepended to the release label version. |
