"""Tests for _get_escalation_info prio-list / escalation flagging."""

from t5gweb.cache import PRIO_ISSUE_STATUS, _get_escalation_info

CFG = {"jira_escalations_project": "RHOCPPRIO"}


def _issue(issue_id, status, url=None):
    return {
        "id": issue_id,
        "status": status,
        "url": url or f"https://jira.example.com/browse/{issue_id}",
    }


def test_prio_issue_in_progress_flags_case():
    """A RHOCPPRIO issue that is In Progress puts the case on the prio-list."""
    issues = [_issue("RHOCPPRIO-1234", PRIO_ISSUE_STATUS)]

    result = _get_escalation_info("01234567", None, issues, [], CFG)

    assert result["escalated"] is True
    assert result["escalated_link"] == "https://jira.example.com/browse/RHOCPPRIO-1234"


def test_prio_issue_not_in_progress_does_not_flag():
    """A RHOCPPRIO issue in another status does not flag the case."""
    issues = [_issue("RHOCPPRIO-1234", "Closed")]

    result = _get_escalation_info("01234567", None, issues, [], CFG)

    assert result["escalated"] is False


def test_non_prio_issue_ignored():
    """An in-progress issue from a different project is not a prio signal."""
    issues = [_issue("OCPBUGS-42", PRIO_ISSUE_STATUS)]

    result = _get_escalation_info("01234567", None, issues, [], CFG)

    assert result["escalated"] is False
    assert result["escalated_link"] is None


def test_escalations_list_still_flags_without_issues():
    """Existing behavior: membership in the escalations list flags the case."""
    result = _get_escalation_info("01234567", ["01234567"], None, [], CFG)

    assert result["escalated"] is True


def test_escalated_link_prefers_first_matching_issue():
    """escalated_link keeps first-match semantics for the escalations project."""
    issues = [
        _issue("RHOCPPRIO-1", "Closed"),
        _issue("RHOCPPRIO-2", PRIO_ISSUE_STATUS),
    ]

    result = _get_escalation_info("01234567", None, issues, [], CFG)

    assert result["escalated"] is True
    # first RHOCPPRIO issue wins the link, even though the second is the prio one
    assert result["escalated_link"] == "https://jira.example.com/browse/RHOCPPRIO-1"


def test_missing_status_is_safe():
    """Issues without a status field do not raise and do not flag."""
    issues = [{"id": "RHOCPPRIO-9", "url": "https://jira.example.com/browse/x"}]

    result = _get_escalation_info("01234567", None, issues, [], CFG)

    assert result["escalated"] is False
