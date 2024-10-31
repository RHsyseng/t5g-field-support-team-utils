import pytest
from t5gweb.utils import exists_or_zero, get_random_member, set_defaults


@pytest.mark.parametrize(
    "data, key, expected",
    [
        ({"test": "result"}, "test", "result"),
        ({"test": "result"}, "not in dictionary", 0),
        ({}, "empty", 0),
        ({"test": "result"}, "", 0),
    ],
)
def test_exists_or_zero(data, key, expected):
    data_point = exists_or_zero(data, key)
    assert data_point == expected


@pytest.fixture
def sample_team():
    return ["Alice", "Bob", "Charlie", "David"]


def test_get_random_member_basic(sample_team):
    result = get_random_member(sample_team)
    assert result in sample_team


def test_get_random_member_avoid_same_person_twice(sample_team):
    first_choice = get_random_member(sample_team)
    second_choice = get_random_member(sample_team, last_choice=first_choice)

    assert first_choice in sample_team
    assert second_choice in sample_team
    assert first_choice != second_choice


def test_get_random_member_single_member():
    team = ["Alice"]
    result = get_random_member(team)
    assert result == "Alice"


def test_get_random_member_empty_team_with_warning(caplog):
    team = []
    result = get_random_member(team)
    assert result is None
    assert "No team variable is available, cannot assign case." in caplog.text


def test_set_default():
    defaults = set_defaults()
    assert defaults["smtp"] == "localhost"
    assert defaults["from"] == "dashboard@example.com"
    assert defaults["to"] == ""
    assert defaults["alert_email"] == "root@localhost"
    assert defaults["subject"] == "New Card(s) Have Been Created to Track Issues"
    assert defaults["sprintname"] == ""
    assert defaults["server"] == ""
    assert defaults["project"] == ""
    assert defaults["component"] == ""
    assert defaults["board"] == ""
    assert defaults["email"] == ""
    assert defaults["type"] == "Story"
    assert defaults["labels"] == ""
    assert defaults["priority"] == "High"
    assert defaults["points"] == 3
    assert defaults["password"] == ""
    assert defaults["card_action"] == "none"
    assert defaults["debug"] == "False"
    assert defaults["team"] == []
    assert defaults["fields"] == [
        "case_account_name",
        "case_summary",
        "case_number",
        "case_status",
        "case_owner",
        "case_severity",
        "case_createdDate",
        "case_lastModifiedDate",
        "case_bugzillaNumber",
        "case_description",
        "case_tags",
        "case_product",
        "case_version",
        "case_closedDate",
    ]
    assert defaults["slack_token"] == ""
    assert defaults["slack_channel"] == ""
    assert defaults["max_jira_results"] == 1000
    assert defaults["max_portal_results"] == 5000
