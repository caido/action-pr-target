import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LINEAR_API_URL = "https://api.linear.app/graphql"
ISSUE_QUERY = """
query($id: String!) {
  issue(id: $id) {
    identifier
    releases(first: 2) {
      nodes {
        name
        version
        stage { type }
      }
      pageInfo { hasNextPage }
    }
  }
}
"""
RELEASE_NAME_PATTERN = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)$", re.IGNORECASE)
PULL_REQUEST_PATH_PATTERN = re.compile(r"^/([^/]+)/([^/]+)/pulls?/([0-9]+)/?$")


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_issue_identifier(branch: str, teams: list[str]) -> str | None:
    teams_pattern = "|".join(re.escape(team) for team in teams)
    pattern = rf"^[a-zA-Z0-9._-]+/(({teams_pattern})-[0-9]+)-[a-zA-Z0-9._-]+$"
    match = re.match(pattern, branch, re.IGNORECASE)
    return match.group(1).upper() if match else None


def fetch_issue_releases(identifier: str, access_key: str) -> list[dict]:
    body = json.dumps({"query": ISSUE_QUERY, "variables": {"id": identifier}}).encode()
    request = urllib.request.Request(
        LINEAR_API_URL,
        data=body,
        headers={"Authorization": access_key, "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Unable to retrieve Linear issue '{identifier}': {error}"
        ) from error

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(error.get("message", "Unknown error") for error in errors)
        raise ValueError(f"Linear API error for '{identifier}': {messages}")

    try:
        issue = payload["data"]["issue"]
        connection = issue["releases"]
        if connection["pageInfo"]["hasNextPage"]:
            raise ValueError(
                f"Linear issue '{identifier}' has more than 2 associated releases"
            )
        releases = []
        for node in connection["nodes"]:
            stage = node.get("stage") or {}
            releases.append(
                {
                    "name": node.get("name") or "",
                    "version": node.get("version"),
                    "stage": stage.get("type") if isinstance(stage, dict) else None,
                }
            )
        return releases
    except (KeyError, TypeError, AttributeError):
        raise ValueError(
            f"Linear issue '{identifier}' was not found or returned an invalid response"
        ) from None


def fetch_pull_request(
    pr_url: str, access_token: str, github_server_url: str = "https://github.com"
) -> tuple[str, str, str]:
    parsed_url = urllib.parse.urlparse(pr_url)
    match = PULL_REQUEST_PATH_PATTERN.fullmatch(parsed_url.path)
    allowed_hosts = {"github.com", urllib.parse.urlparse(github_server_url).hostname}
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.hostname.lower() not in allowed_hosts
        or parsed_url.username
        or parsed_url.password
        or match is None
    ):
        raise ValueError(
            "Invalid pull request URL. Expected a GitHub URL like "
            "https://github.com/owner/repository/pull/123."
        )

    owner, repository, number = match.groups()
    if parsed_url.hostname.lower() == "github.com":
        api_url = f"https://api.github.com/repos/{owner}/{repository}/pulls/{number}"
    else:
        api_url = (
            f"{parsed_url.scheme}://{parsed_url.netloc}/api/v3/repos/"
            f"{owner}/{repository}/pulls/{number}"
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(api_url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Unable to retrieve pull request '{pr_url}': {error}"
        ) from error

    try:
        branch = payload["head"]["ref"]
        target = payload["base"]["ref"]
        if not isinstance(branch, str) or not isinstance(target, str):
            raise TypeError
        return branch, target, f"{owner}/{repository}"
    except (KeyError, TypeError):
        raise ValueError(
            f"Pull request '{pr_url}' was not found or returned an invalid response"
        ) from None


def release_name_version(name: object) -> str | None:
    if not isinstance(name, str):
        return None
    match = RELEASE_NAME_PATTERN.fullmatch(name.strip())
    return match.group(1) if match else None


def format_releases(releases: list[dict]) -> str:
    if not releases:
        return "(none)"
    parts = []
    for release in releases:
        name = release.get("name") or "(unnamed)"
        version = release.get("version") or "(no version)"
        stage = release.get("stage") or "unknown"
        parts.append(f"{name} {version} [{stage}]")
    return ", ".join(parts)


def release_branch_exists(
    repository: str,
    branch: str,
    access_token: str,
    github_api_url: str = "https://api.github.com",
) -> bool:
    if not access_token:
        raise ValueError("GitHub token is not configured.")

    owner, separator, repo = repository.partition("/")
    if not separator or not owner or not repo or "/" in repo:
        raise ValueError(
            f"Invalid GitHub repository '{repository}'. Expected 'owner/repository'."
        )

    api_root = github_api_url.rstrip("/")
    repository_url = f"{api_root}/repos/{owner}/{repo}"
    quoted_branch = urllib.parse.quote(branch, safe="")
    branch_url = f"{repository_url}/branches/{quoted_branch}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def github_status(url: str) -> int:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
                return 200
        except urllib.error.HTTPError as error:
            return error.code
        except (urllib.error.URLError, TimeoutError) as error:
            raise ValueError(
                f"Unable to check whether branch '{branch}' exists in '{repository}': {error}"
            ) from error

    repository_status = github_status(repository_url)
    if repository_status != 200:
        raise ValueError(
            f"Unable to check whether branch '{branch}' exists in '{repository}': "
            f"HTTP {repository_status}"
        )

    branch_status = github_status(branch_url)
    if branch_status == 404:
        return False
    if branch_status == 200:
        return True
    raise ValueError(
        f"Unable to check whether branch '{branch}' exists in '{repository}': "
        f"HTTP {branch_status}"
    )


def expected_target(
    releases: list[dict], default_target: str, release_prefix: str
) -> str:
    candidates: list[tuple[str, str, str]] = []
    for release in releases:
        stage = str(release.get("stage") or "").lower()
        if stage in {"canceled", "cancelled"}:
            continue
        name = str(release.get("name") or "")
        version = release_name_version(name)
        if version is None:
            continue
        candidates.append((version, stage, name))

    selected = [item for item in candidates if item[1] != "completed"] or candidates
    versions = {version for version, _, _ in selected}
    if not versions:
        return default_target
    if len(versions) != 1:
        details = ", ".join(
            f"{name} ({version})"
            for version, _, name in sorted(selected, key=lambda item: (item[0], item[2]))
        )
        raise ValueError(f"Conflicting releases: {details}")

    return f"{release_prefix}{versions.pop()}"


def validate(
    branch: str,
    target: str,
    access_key: str,
    teams_raw: str,
    default_target: str,
    release_prefix: str,
    *,
    repository: str = "",
    github_token: str = "",
    github_api_url: str = "https://api.github.com",
) -> bool:
    print(f"PR head branch: {branch}")
    print(f"PR target branch: {target}")
    identifier = extract_issue_identifier(branch, parse_list(teams_raw))
    if identifier is None:
        print("No matching Linear issue identifier found; target validation skipped.")
        return True

    print(f"Linear issue: {identifier}")
    if not access_key:
        print("::error::Linear access key is not configured.")
        return False

    try:
        releases = fetch_issue_releases(identifier, access_key)
        print(f"Linear releases: {format_releases(releases)}")
        expected = expected_target(releases, default_target, release_prefix)
        if expected != default_target and not release_branch_exists(
            repository, expected, github_token, github_api_url
        ):
            print(
                f"Release branch '{expected}' does not exist; "
                f"required target falls back to '{default_target}'."
            )
            expected = default_target
    except ValueError as error:
        print(f"::error::{error}")
        return False

    print(f"Required target: {expected}")
    print(f"Actual target: {target}")
    if target != expected:
        print(
            f"::error::Linear issue '{identifier}' requires target '{expected}' instead of '{target}'."
        )
        return False

    print(f"PR targets '{expected}' as required by Linear issue '{identifier}'.")
    return True


def main() -> None:
    branch = os.environ.get("BRANCH", "")
    target = os.environ.get("TARGET", "")
    access_key = os.environ.get("LINEAR_ACCESS_KEY", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    pr_url = os.environ.get("PR_URL", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    github_api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    teams = os.environ.get("TEAMS", "ENG,MAN,SUP")
    default_target = os.environ.get("DEFAULT_TARGET", "dev")
    release_prefix = os.environ.get("RELEASE_PREFIX", "release/v")

    if dry_run:
        if not pr_url:
            print("::error::A PR URL is required when dry-run is enabled.")
            sys.exit(1)
        try:
            branch, target, repository = fetch_pull_request(
                pr_url, github_token, github_server_url
            )
        except ValueError as error:
            print(f"::error::{error}")
            sys.exit(1)
        print(f"Dry run for {pr_url}: head '{branch}' targets '{target}'.")

    if not branch:
        print("::error::No branch name provided.")
        sys.exit(1)
    if not target:
        print("::error::No target branch provided.")
        sys.exit(1)

    if not validate(
        branch,
        target,
        access_key,
        teams,
        default_target,
        release_prefix,
        repository=repository,
        github_token=github_token,
        github_api_url=github_api_url,
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
