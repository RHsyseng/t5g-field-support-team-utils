import pytest

from t5gweb.utils import exists_or_zero, set_defaults


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
    assert defaults["high_severity_slack_channel"] == ""
    assert defaults["low_severity_slack_channel"] == ""
    assert defaults["max_jira_results"] is False
    assert defaults["max_portal_results"] == 5000
