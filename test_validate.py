import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from validate import (
    expected_target,
    extract_issue_identifier,
    fetch_issue_labels,
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


class TestExpectedTarget:
    def test_no_release_label(self):
        assert expected_target(["bug"], "dev", "release/v") == "dev"

    def test_release_label(self):
        assert (
            expected_target(["bug", "release:0.59.0"], "dev", "release/v")
            == "release/v0.59.0"
        )

    def test_case_insensitive_release_label(self):
        assert (
            expected_target(["RELEASE:0.59.0"], "dev", "release/v") == "release/v0.59.0"
        )

    def test_duplicate_equivalent_release_labels(self):
        assert (
            expected_target(["release:0.59.0", "RELEASE:0.59.0"], "dev", "release/v")
            == "release/v0.59.0"
        )

    def test_malformed_release_label(self):
        with pytest.raises(ValueError, match="Invalid release label"):
            expected_target(["release:v0.59.0"], "dev", "release/v")

    def test_conflicting_release_labels(self):
        with pytest.raises(ValueError, match="Conflicting release labels"):
            expected_target(["release:0.59.0", "release:0.60.0"], "dev", "release/v")


class TestFetchIssueLabels:
    @patch("urllib.request.urlopen")
    def test_success(self, urlopen):
        urlopen.return_value = Response(
            {
                "data": {
                    "issue": {
                        "identifier": "ENG-1234",
                        "labels": {"nodes": [{"name": "bug"}]},
                    }
                }
            }
        )
        assert fetch_issue_labels("ENG-1234", "secret") == ["bug"]

        request = urlopen.call_args.args[0]
        assert request.headers["Authorization"] == "secret"
        assert json.loads(request.data)["variables"] == {"id": "ENG-1234"}

    @patch("urllib.request.urlopen")
    def test_graphql_error(self, urlopen):
        urlopen.return_value = Response({"errors": [{"message": "Unauthorized"}]})
        with pytest.raises(ValueError, match="Unauthorized"):
            fetch_issue_labels("ENG-1234", "secret")

    @patch("urllib.request.urlopen")
    def test_missing_issue(self, urlopen):
        urlopen.return_value = Response({"data": {"issue": None}})
        with pytest.raises(ValueError, match="not found"):
            fetch_issue_labels("ENG-1234", "secret")

    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline"))
    def test_network_error(self, _urlopen):
        with pytest.raises(ValueError, match="Unable to retrieve"):
            fetch_issue_labels("ENG-1234", "secret")


class TestValidate:
    @patch("validate.fetch_issue_labels", return_value=["bug"])
    def test_no_release_label_targets_dev(self, _fetch):
        assert validate(
            "chris/ENG-1234-description",
            "dev",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch("validate.fetch_issue_labels", return_value=["bug"])
    def test_no_release_label_rejects_other_target(self, _fetch):
        assert not validate(
            "chris/ENG-1234-description",
            "main",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch("validate.fetch_issue_labels", return_value=["release:0.59.0"])
    def test_release_label_targets_release(self, _fetch):
        assert validate(
            "chris/ENG-1234-description",
            "release/v0.59.0",
            "secret",
            "ENG,MAN,SUP",
            "dev",
            "release/v",
        )

    @patch("validate.fetch_issue_labels", return_value=["release:0.59.0"])
    def test_release_label_rejects_dev(self, _fetch):
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
