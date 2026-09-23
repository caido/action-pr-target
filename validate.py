import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LINEAR_API_URL = "https://api.linear.app/graphql"
ISSUE_QUERY = (
    "query($id: String!) { issue(id: $id) { identifier labels { nodes { name } } } }"
)
RELEASE_LABEL_PATTERN = re.compile(
    r"^(?:release:)?([0-9]+\.[0-9]+\.[0-9]+)$", re.IGNORECASE
)
PULL_REQUEST_PATH_PATTERN = re.compile(r"^/([^/]+)/([^/]+)/pulls?/([0-9]+)/?$")


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_issue_identifier(branch: str, teams: list[str]) -> str | None:
    teams_pattern = "|".join(re.escape(team) for team in teams)
    pattern = rf"^[a-zA-Z0-9._-]+/(({teams_pattern})-[0-9]+)-[a-zA-Z0-9._-]+$"
    match = re.match(pattern, branch, re.IGNORECASE)
    return match.group(1).upper() if match else None


def fetch_issue_labels(identifier: str, access_key: str) -> list[str]:
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
        nodes = payload["data"]["issue"]["labels"]["nodes"]
        return [node["name"] for node in nodes]
    except (KeyError, TypeError):
        raise ValueError(
            f"Linear issue '{identifier}' was not found or returned an invalid response"
        ) from None


def fetch_pull_request(
    pr_url: str, access_token: str, github_server_url: str = "https://github.com"
) -> tuple[str, str]:
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
        return branch, target
    except (KeyError, TypeError):
        raise ValueError(
            f"Pull request '{pr_url}' was not found or returned an invalid response"
        ) from None


def expected_target(labels: list[str], default_target: str, release_prefix: str) -> str:
    release_labels = [
        label
        for label in labels
        if label.lower().startswith("release:") or RELEASE_LABEL_PATTERN.fullmatch(label)
    ]
    if not release_labels:
        return default_target

    versions: set[str] = set()
    for label in release_labels:
        match = RELEASE_LABEL_PATTERN.fullmatch(label)
        if match is None:
            raise ValueError(
                f"Invalid release label '{label}'. Expected X.Y.Z or release:X.Y.Z"
            )
        versions.add(match.group(1))

    if len(versions) != 1:
        raise ValueError(f"Conflicting release labels: {', '.join(release_labels)}")

    return f"{release_prefix}{versions.pop()}"


def validate(
    branch: str,
    target: str,
    access_key: str,
    teams_raw: str,
    default_target: str,
    release_prefix: str,
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
        labels = fetch_issue_labels(identifier, access_key)
        print(f"Linear labels: {', '.join(labels) if labels else '(none)'}")
        expected = expected_target(labels, default_target, release_prefix)
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
    teams = os.environ.get("TEAMS", "ENG,MAN,SUP")
    default_target = os.environ.get("DEFAULT_TARGET", "dev")
    release_prefix = os.environ.get("RELEASE_PREFIX", "release/v")

    if dry_run:
        if not pr_url:
            print("::error::A PR URL is required when dry-run is enabled.")
            sys.exit(1)
        try:
            branch, target = fetch_pull_request(pr_url, github_token, github_server_url)
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

    if not validate(branch, target, access_key, teams, default_target, release_prefix):
        sys.exit(1)


if __name__ == "__main__":
    main()
