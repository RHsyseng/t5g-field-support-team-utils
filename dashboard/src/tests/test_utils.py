import pytest

from t5gweb.cache import build_where, remap_case_status
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


@pytest.mark.parametrize(
    "status, expected",
    [
        # Customer-side waits collapse to the "Waiting on Customer" bucket.
        ("Waiting on Customer", "Waiting on Customer"),
        ("Waiting on Customer Action Required", "Waiting on Customer"),
        # Closed stays closed.
        ("Closed", "Closed"),
        # Every Red-Hat-side status collapses to "Waiting on Red Hat".
        ("Waiting on Red Hat", "Waiting on Red Hat"),
        ("Waiting on Engineering", "Waiting on Red Hat"),
        ("In Progress", "Waiting on Red Hat"),
        ("Waiting on Collab", "Waiting on Red Hat"),
        ("Waiting on 3rd Party Vendor", "Waiting on Red Hat"),
        ("Needs New Owner", "Waiting on Red Hat"),
        ("Deferred", "Waiting on Red Hat"),
        # Unknown / missing statuses default to the Red Hat bucket so the table
        # view never KeyErrors.
        ("Some New Status", "Waiting on Red Hat"),
        (None, "Waiting on Red Hat"),
        ("", "Waiting on Red Hat"),
    ],
)
def test_remap_case_status(status, expected):
    assert remap_case_status(status) == expected


def test_build_where_full_saved_search():
    saved_search = {
        "products": ["OpenShift Container Platform", "Advanced Cluster Management"],
        "subject_contains": ["[ExampleTag]", "[AnotherTag]"],
        "account_branches": [
            {"accounts": ["1234567", "2345678"], "product": True},
            {"accounts": ["3456789"], "product": False},
        ],
    }
    where = build_where(saved_search)

    # open_only wraps the OR in an AND with IsClosed: {eq: False}
    assert where == {
        "and": [
            {"IsClosed": {"eq": False}},
            {
                "or": [
                    {
                        "or": [
                            {"Subject": {"like": "%[ExampleTag]%"}},
                            {"Subject": {"like": "%[AnotherTag]%"}},
                        ]
                    },
                    {
                        "and": [
                            {"Account_Number__c": {"in": ["1234567", "2345678"]}},
                            {
                                "or": [
                                    {
                                        "Product": {
                                            "Name": {
                                                "like": "%OpenShift Container Platform%"
                                            }
                                        }
                                    },
                                    {
                                        "Product": {
                                            "Name": {
                                                "like": "%Advanced Cluster Management%"
                                            }
                                        }
                                    },
                                ]
                            },
                        ]
                    },
                    {"Account_Number__c": {"eq": "3456789"}},
                ]
            },
        ]
    }


def test_build_where_single_account_uses_eq():
    saved_search = {
        "products": ["OpenShift Container Platform"],
        "subject_contains": [],
        "account_branches": [{"accounts": ["3456789"], "product": False}],
    }
    where = build_where(saved_search, open_only=False)

    # no subject block, single account -> eq, no IsClosed wrapper
    assert where == {"or": [{"Account_Number__c": {"eq": "3456789"}}]}
