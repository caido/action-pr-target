import json
import os
import re
import sys
import urllib.error
import urllib.request

LINEAR_API_URL = "https://api.linear.app/graphql"
ISSUE_QUERY = "query($id: String!) { issue(id: $id) { identifier labels { nodes { name } } } }"
RELEASE_LABEL_PATTERN = re.compile(r"^release:([0-9]+\.[0-9]+\.[0-9]+)$", re.IGNORECASE)


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
        raise ValueError(f"Unable to retrieve Linear issue '{identifier}': {error}") from error

    errors = payload.get("errors")
    if errors:
        messages = "; ".join(error.get("message", "Unknown error") for error in errors)
        raise ValueError(f"Linear API error for '{identifier}': {messages}")

    try:
        nodes = payload["data"]["issue"]["labels"]["nodes"]
        return [node["name"] for node in nodes]
    except (KeyError, TypeError):
        raise ValueError(f"Linear issue '{identifier}' was not found or returned an invalid response") from None


def expected_target(labels: list[str], default_target: str, release_prefix: str) -> str:
    release_labels = [label for label in labels if label.lower().startswith("release:")]
    if not release_labels:
        return default_target

    versions: set[str] = set()
    for label in release_labels:
        match = RELEASE_LABEL_PATTERN.fullmatch(label)
        if match is None:
            raise ValueError(f"Invalid release label '{label}'. Expected release:X.Y.Z")
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
    identifier = extract_issue_identifier(branch, parse_list(teams_raw))
    if identifier is None:
        print(f"Branch '{branch}' has no Linear issue to check.")
        return True

    if not access_key:
        print("::error::Linear access key is not configured.")
        return False

    try:
        labels = fetch_issue_labels(identifier, access_key)
        expected = expected_target(labels, default_target, release_prefix)
    except ValueError as error:
        print(f"::error::{error}")
        return False

    if target != expected:
        print(f"::error::Linear issue '{identifier}' requires target '{expected}' instead of '{target}'.")
        return False

    print(f"PR targets '{expected}' as required by Linear issue '{identifier}'.")
    return True


def main() -> None:
    branch = os.environ.get("BRANCH", "")
    target = os.environ.get("TARGET", "")
    access_key = os.environ.get("LINEAR_ACCESS_KEY", "")
    teams = os.environ.get("TEAMS", "ENG,MAN,SUP")
    default_target = os.environ.get("DEFAULT_TARGET", "dev")
    release_prefix = os.environ.get("RELEASE_PREFIX", "release/v")

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
