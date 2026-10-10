"""
Tests for the My Queue view feature.

Tests cover get_my_queue_cases() from t5gweb.database.operations,
which is the core business logic behind the /my-queue route.
"""

from datetime import datetime, timedelta, timezone

from t5gweb.database import Case, Comment, JiraCard, JiraComment
from t5gweb.database.operations import get_my_queue_cases

CASE_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _case(case_number="10000001", status="Open", severity=3, **kwargs):
    defaults = dict(
        owner="Test Owner",
        account="Test Account",
        summary=f"Summary for {case_number}",
        created_date=CASE_DATE,
        last_update=CASE_DATE,
        description="desc",
        product="Product 1.0",
        product_version="1.0",
    )
    defaults.update(kwargs)
    return Case(case_number=case_number, status=status, severity=severity, **defaults)


def _card(
    jira_card_id="CARD-1",
    case_number="10000001",
    assignee="engineer1",
    sprint="Sprint 1",
    **kwargs,
):
    defaults = dict(
        created_date=CASE_DATE,
        last_update_date=CASE_DATE,
        summary=f"{jira_card_id}: summary",
        priority="High",
        status="In Progress",
        severity=3,
    )
    defaults.update(kwargs)
    return JiraCard(
        jira_card_id=jira_card_id,
        case_number=case_number,
        assignee=assignee,
        sprint=sprint,
        **defaults,
    )


def _portal_comment(
    case_number="10000001",
    commented_at=None,
    author="customer1",
    text="portal comment",
    comment_type=None,
):
    if commented_at is None:
        commented_at = CASE_DATE + timedelta(days=1)
    return Comment(
        case_number=case_number,
        created_date=CASE_DATE,
        author=author,
        comment_type=comment_type,
        comment_text=text,
        commented_at=commented_at,
    )


def _jira_comment(
    jira_card_id="CARD-1",
    jira_comment_id="jc-1",
    last_update_date=None,
    author="eng1",
    body="jira comment",
):
    if last_update_date is None:
        last_update_date = CASE_DATE + timedelta(days=1)
    return JiraComment(
        jira_comment_id=jira_comment_id,
        jira_card_id=jira_card_id,
        author=author,
        body=body,
        last_update_date=last_update_date,
    )


def _seed(session, objects):
    for obj in objects:
        session.add(obj)
    session.commit()


class TestGetMyQueueCasesInclusion:
    """Test which cases are included/excluded based on comment timestamps."""

    def test_portal_comment_newer_than_jira_included(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=5)),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=3)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_jira_comment_newer_than_portal_excluded(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=1)),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=3)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result

    def test_jira_comment_same_time_as_portal_excluded(self, test_db_session):
        ts = CASE_DATE + timedelta(days=2)
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=ts),
                _jira_comment(last_update_date=ts),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result

    def test_no_jira_comments_included(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_no_jira_comments_no_portal_comments_included(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_no_portal_comments_with_jira_comment_excluded(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=1)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result

    def test_closed_case_excluded(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(status="Closed"),
                _card(),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result

    def test_case_without_jira_card_excluded(self, test_db_session):
        _seed(test_db_session, [_case()])

        result = get_my_queue_cases()
        assert "10000001" not in result


class TestGetMyQueueCasesFilters:
    """Test sprint and engineer filtering."""

    def _seed_two_cases(self, session):
        _seed(
            session,
            [
                _case(case_number="10000001"),
                _card(
                    jira_card_id="CARD-1",
                    case_number="10000001",
                    assignee="Alice",
                    sprint="Sprint 1",
                ),
                _case(case_number="10000002"),
                _card(
                    jira_card_id="CARD-2",
                    case_number="10000002",
                    assignee="Bob",
                    sprint="Sprint 2",
                ),
            ],
        )

    def test_filter_by_sprint(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(active_sprint_name="Sprint 1")
        assert "10000001" in result
        assert "10000002" not in result

    def test_filter_by_engineer(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(engineer_filter="Bob")
        assert "10000002" in result
        assert "10000001" not in result

    def test_filter_by_both_sprint_and_engineer(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(
            active_sprint_name="Sprint 1",
            engineer_filter="Alice",
        )
        assert "10000001" in result
        assert len(result) == 1

    def test_filter_by_both_no_match(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(
            active_sprint_name="Sprint 1",
            engineer_filter="Bob",
        )
        assert len(result) == 0

    def test_no_filters_returns_all(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases()
        assert len(result) == 2

    def test_nonexistent_sprint_returns_empty(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(active_sprint_name="Sprint 999")
        assert len(result) == 0

    def test_nonexistent_engineer_returns_empty(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(engineer_filter="Nobody")
        assert len(result) == 0


class TestGetMyQueueCasesReturnStructure:
    """Test the shape and content of returned data."""

    def test_returned_keys(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(case_number="10000001", severity=2, summary="Important case"),
                _card(assignee="Alice", status="In Progress"),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=5),
                    author="cust",
                    text="Please help",
                ),
                _jira_comment(
                    last_update_date=CASE_DATE + timedelta(days=3),
                    author="eng",
                    body="Working on it",
                ),
            ],
        )

        result = get_my_queue_cases()
        case = result["10000001"]

        assert case["case_number"] == "10000001"
        assert case["severity"] == 2
        assert case["summary"] == "Important case"
        assert case["field_engineer"] == "Alice"
        assert case["portal_status"] == "Open"
        assert case["jira_status"] == "In Progress"
        assert isinstance(case["portal_comments"], list)
        assert isinstance(case["jira_comments"], list)
        assert case["most_recent_jira_comment"] is not None

    def test_portal_comment_structure(self, test_db_session):
        ts = CASE_DATE + timedelta(days=5)
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=ts, author="customer", text="Help me"),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=3)),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        pc = case["portal_comments"][0]
        assert pc["author"] == "customer"
        assert pc["body"] == "Help me"
        assert "2024-01-06T00:00:00" in pc["date"]

    def test_jira_comment_structure(self, test_db_session):
        ts = CASE_DATE + timedelta(days=3)
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=5)),
                _jira_comment(last_update_date=ts, author="dev", body="Fixed"),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        jc = case["jira_comments"][0]
        assert jc["author"] == "dev"
        assert jc["body"] == "Fixed"
        assert "2024-01-04T00:00:00" in jc["updated"]

    def test_most_recent_jira_comment_is_newest(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=10)),
                _jira_comment(
                    jira_comment_id="jc-old",
                    last_update_date=CASE_DATE + timedelta(days=1),
                    body="old",
                ),
                _jira_comment(
                    jira_comment_id="jc-new",
                    last_update_date=CASE_DATE + timedelta(days=5),
                    body="new",
                ),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        assert case["most_recent_jira_comment"]["body"] == "new"

    def test_no_jira_comments_most_recent_is_none(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        assert case["most_recent_jira_comment"] is None
        assert case["jira_comments"] == []

    def test_comments_ordered_newest_first(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=10), text="newest"
                ),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=1),
                    text="oldest",
                    author="customer2",
                ),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        assert case["portal_comments"][0]["body"] == "newest"
        assert case["portal_comments"][1]["body"] == "oldest"


class TestGetMyQueueCasesEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_database(self, test_db_session):
        result = get_my_queue_cases()
        assert result == {}

    def test_multiple_jira_cards_for_same_case(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(case_number="10000001"),
                _card(jira_card_id="CARD-A", case_number="10000001", sprint="Sprint 1"),
                _card(jira_card_id="CARD-B", case_number="10000001", sprint="Sprint 2"),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_case_with_many_comments(self, test_db_session):
        objects = [_case(), _card()]
        for i in range(20):
            objects.append(
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=i + 1),
                    text=f"comment {i}",
                    author=f"author{i}",
                )
            )
        _seed(test_db_session, objects)

        result = get_my_queue_cases()
        case = result["10000001"]
        assert len(case["portal_comments"]) == 20
        assert case["portal_comments"][0]["body"] == "comment 19"

    def test_various_non_closed_statuses_included(self, test_db_session):
        statuses = ["Open", "Waiting on Red Hat", "Waiting on Customer"]
        for i, status in enumerate(statuses):
            cn = f"1000000{i + 1}"
            _seed(
                test_db_session,
                [
                    _case(case_number=cn, status=status),
                    _card(jira_card_id=f"CARD-{i}", case_number=cn),
                ],
            )

        result = get_my_queue_cases()
        assert len(result) == 3

    def test_null_sprint_card_returned_without_sprint_filter(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(sprint=None),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_null_sprint_card_excluded_with_sprint_filter(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(sprint=None),
            ],
        )

        result = get_my_queue_cases(active_sprint_name="Sprint 1")
        assert "10000001" not in result

    def test_null_assignee_excluded_with_engineer_filter(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(assignee=None),
            ],
        )

        result = get_my_queue_cases(engineer_filter="Alice")
        assert "10000001" not in result

    def test_null_assignee_returned_without_filter(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(assignee=None),
            ],
        )

        result = get_my_queue_cases()
        case = result["10000001"]
        assert case["field_engineer"] is None
