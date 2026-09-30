import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from validate import (
    expected_target,
    extract_issue_identifier,
    fetch_issue_releases,
    parse_list,
    validate,
)


class Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode())

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class TestParseList:
    def test_values(self):
        assert parse_list(" ENG, MAN, SUP ") == ["ENG", "MAN", "SUP"]


class TestExtractIssueIdentifier:
    def test_valid_branch(self):
        assert (
            extract_issue_identifier(
                "chris/eng-1234-description", ["ENG", "MAN", "SUP"]
            )
            == "ENG-1234"
        )

    def test_invalid_branch(self):
        assert extract_issue_identifier("bad-branch", ["ENG", "MAN", "SUP"]) is None


def release(
    name: str, stage: str | None = "started", version: str | None = None
):
    return {"name": name, "version": version, "stage": stage}


class TestExpectedTarget:
    def test_no_release(self):
        assert expected_target([], "dev", "release/v") == "dev"

    def test_release_name(self):
        assert (
            expected_target([release("v0.59.0", version="0.59.0-rc.1")], "dev", "release/v")
            == "release/v0.59.0"
        )

    def test_version_field_is_ignored(self):
        assert (
            expected_target([release("v0.55.0", version="v0.58.0")], "dev", "release/v")
            == "release/v0.55.0"
        )

    def test_name_without_v_prefix_is_ignored(self):
        assert expected_target([release("0.59.0")], "dev", "release/v") == "dev"

    def test_duplicate_equivalent_names(self):
        assert (
            expected_target(
                [release("v0.59.0"), release("V0.59.0")],
                "dev",
                "release/v",
            )
            == "release/v0.59.0"
        )

    def test_non_version_name_is_ignored(self):
        assert (
            expected_target([release("abc1234", stage="completed")], "dev", "release/v")
            == "dev"
        )

    def test_open_release_preferred_over_completed(self):
        assert (
            expected_target(
                [
                    release("v0.59.0", stage="completed"),
                    release("v0.60.0", stage="started"),
                ],
                "dev",
                "release/v",
            )
            == "release/v0.60.0"
        )

    def test_completed_release_used_when_it_is_the_only_version(self):
        assert (
            expected_target([release("v0.59.0", stage="completed")], "dev", "release/v")
            == "release/v0.59.0"
        )

    def test_canceled_release_is_ignored(self):
        assert (
            expected_target([release("v0.59.0", stage="canceled")], "dev", "release/v")
            == "dev"
        )

    def test_conflicting_releases(self):
        with pytest.raises(ValueError, match="Conflicting releases"):
            expected_target(
                [release("v0.59.0"), release("v0.60.0")],
                "dev",
                "release/v",
            )


class TestFetchIssueReleases:
    @patch("urllib.request.urlopen")
    def test_success(self, urlopen):
        urlopen.return_value = Response(
            {
                "data": {
                    "issue": {
                        "identifier": "ENG-1234",
                        "releases": {
                            "nodes": [
                                {
                                    "name": "0.59.0",
                                    "version": "0.59.0",
                                    "stage": {"type": "started"},
                                }
                            ],
                            "pageInfo": {"hasNextPage": False},
                        },
                    }
                }
            }
        )
        assert fetch_issue_releases("ENG-1234", "secret") == [
            {"name": "0.59.0", "version": "0.59.0", "stage": "started"}
        ]

        request = urlopen.call_args.args[0]
        assert request.headers["Authorization"] == "secret"
        assert json.loads(request.data)["variables"] == {"id": "ENG-1234"}

    @patch("urllib.request.urlopen")
    def test_graphql_error(self, urlopen):
        urlopen.return_value = Response({"errors": [{"message": "Unauthorized"}]})
        with pytest.raises(ValueError, match="Unauthorized"):
            fetch_issue_releases("ENG-1234", "secret")

    @patch("urllib.request.urlopen")
    def test_missing_issue(self, urlopen):
        urlopen.return_value = Response({"data": {"issue": None}})
        with pytest.raises(ValueError, match="not found"):
            fetch_issue_releases("ENG-1234", "secret")

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline"))
    def test_network_error(self, _urlopen):
        with pytest.raises(ValueError, match="Unable to retrieve"):
            fetch_issue_releases("ENG-1234", "secret")


class TestValidate:
    @patch("validate.fetch_issue_releases", return_value=[])
    def test_no_release_targets_dev(self, _fetch):
        assert validate(
            "chris/ENG-1234-description",
            "dev",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch("validate.fetch_issue_releases", return_value=[])
    def test_no_release_rejects_other_target(self, _fetch):
        assert not validate(
            "chris/ENG-1234-description",
            "main",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch(
        "validate.fetch_issue_releases",
        return_value=[release("v0.59.0", version="0.59.0-rc.1")],
    )
    def test_release_targets_release_branch(self, _fetch):
        assert validate(
            "chris/ENG-1234-description",
            "release/v0.59.0",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch(
        "validate.fetch_issue_releases",
        return_value=[release("v0.59.0", version="0.59.0-rc.1")],
    )
    def test_release_rejects_dev(self, _fetch):
        assert not validate(
            "chris/ENG-1234-description",
            "dev",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    def test_missing_access_key(self):
        assert not validate(
            "chris/ENG-1234-description", "dev", "", "ENG,MAN,SUP", "dev", "release/v"
        )

    def test_branch_without_issue_skips_lookup(self):
        assert validate("release/v0.59.0", "dev", "", "ENG,MAN,SUP", "dev", "release/v")
