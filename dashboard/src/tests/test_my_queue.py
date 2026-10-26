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


_UNSET = object()


def _card(
    jira_card_id="CARD-1",
    case_number="10000001",
    assignee="engineer1",
    assignee_email=_UNSET,
    sprint="Sprint 1",
    **kwargs,
):
    # My Queue matches on the assignee email; by default mirror the assignee
    # so tests can keep expressing the engineer with a single value.
    if assignee_email is _UNSET:
        assignee_email = assignee
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
        assignee_email=assignee_email,
        sprint=sprint,
        **defaults,
    )


def _portal_comment(
    case_number="10000001",
    commented_at=None,
    author="customer1",
    text="portal comment",
    comment_type=None,
    is_public=None,
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
        is_public=is_public,
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

    def test_no_update_newer_than_portal_excluded(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(no_update_date=CASE_DATE + timedelta(days=5)),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=3)),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=1)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result

    def test_no_update_older_than_portal_included(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(no_update_date=CASE_DATE + timedelta(days=1)),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=3)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" in result

    def test_no_update_newer_than_portal_no_jira_comments_excluded(
        self, test_db_session
    ):
        # Regression: a card marked "no update needed" must be excluded even
        # when it has zero JIRA comments (the check used to live inside the
        # branch that only runs when JIRA comments exist).
        _seed(
            test_db_session,
            [
                _case(),
                _card(no_update_date=CASE_DATE + timedelta(days=5)),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=3)),
            ],
        )

        result = get_my_queue_cases()
        assert "10000001" not in result


class TestGetMyQueueCasesPortalCommentAuthor:
    """Only the customer's portal comments keep a case in the queue."""

    def test_red_hat_portal_reply_does_not_requeue(self, test_db_session):
        # The engineer answered on the portal (Associate) after the JIRA
        # comment. The case is answered, so it must leave the queue instead of
        # being held open by Red Hat's own reply.
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=1),
                    comment_type="Customer",
                    text="please help",
                ),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=2)),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=3),
                    comment_type="Associate",
                    author="engineer1",
                    text="answered on the portal",
                ),
            ],
        )

        assert get_my_queue_cases() == {}

    def test_customer_comment_after_red_hat_reply_requeues(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=2)),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=3),
                    comment_type="Associate",
                    author="engineer1",
                ),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=4),
                    comment_type="Customer",
                    author="customer1",
                ),
            ],
        )

        assert "10000001" in get_my_queue_cases()

    def test_untyped_comment_still_counts(self, test_db_session):
        # Rows synced before comment_type existed carry NULL; treating those as
        # Red Hat's would silently drop cases out of the queue.
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=2)),
                _portal_comment(
                    commented_at=CASE_DATE + timedelta(days=3), comment_type=None
                ),
            ],
        )

        assert "10000001" in get_my_queue_cases()


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

        result = get_my_queue_cases(engineer_email="Bob")
        assert "10000002" in result
        assert "10000001" not in result

    def test_filter_by_both_sprint_and_engineer(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(
            active_sprint_name="Sprint 1",
            engineer_email="Alice",
        )
        assert "10000001" in result
        assert len(result) == 1

    def test_filter_by_both_no_match(self, test_db_session):
        self._seed_two_cases(test_db_session)

        result = get_my_queue_cases(
            active_sprint_name="Sprint 1",
            engineer_email="Bob",
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

        result = get_my_queue_cases(engineer_email="Nobody")
        assert len(result) == 0

    def test_filter_matches_on_email_not_display_name(self, test_db_session):
        # Regression: the engineer filter must match the assignee email, not
        # the display name. A user whose SAML login omits the surname (so the
        # display name differs from JIRA) must still find their cards by email.
        _seed(
            test_db_session,
            [
                _case(case_number="10000001"),
                _card(
                    case_number="10000001",
                    assignee="Firstname Lastname",
                    assignee_email="engineer@example.com",
                ),
            ],
        )

        # Matching by the display name must NOT work...
        assert get_my_queue_cases(engineer_email="Firstname") == {}
        # ...but matching by email must.
        result = get_my_queue_cases(engineer_email="engineer@example.com")
        assert "10000001" in result

    def test_engineer_filter_is_case_insensitive(self, test_db_session):
        # SAML sends Firstname.Lastname@redhat.com where JIRA stores the
        # lowercase form (or the reverse); an exact match would hand the
        # engineer an empty queue with no error.
        _seed(
            test_db_session,
            [
                _case(case_number="10000001"),
                _card(
                    case_number="10000001",
                    assignee_email="Engineer.One@example.com",
                ),
            ],
        )

        assert "10000001" in get_my_queue_cases(
            engineer_email="engineer.one@example.com"
        )
        assert "10000001" in get_my_queue_cases(
            engineer_email="ENGINEER.ONE@EXAMPLE.COM"
        )

    def test_empty_engineer_email_returns_nothing(self, test_db_session):
        # An authenticated user with no mail attribute must not be shown every
        # engineer's queue; "" is a filter that matches nothing, not "no filter".
        self._seed_two_cases(test_db_session)

        assert get_my_queue_cases(engineer_email="") == {}


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
        assert case["jira_card_id"] == "CARD-1"
        assert case["most_recent_jira_comment"] is not None

    def test_comment_bodies_not_loaded_into_the_row(self, test_db_session):
        # The table never renders the histories (the expanded row fetches them
        # on demand), so they must not be materialised per case here.
        _seed(
            test_db_session,
            [
                _case(),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=5)),
                _jira_comment(last_update_date=CASE_DATE + timedelta(days=3)),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        assert "portal_comments" not in case
        assert "jira_comments" not in case

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
        jc = case["most_recent_jira_comment"]
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
        assert "10000001" in result

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

        result = get_my_queue_cases(engineer_email="Alice")
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


class TestGetMyQueueCasesMultipleCards:
    """A case is judged once, across every card tracking it."""

    def test_answered_case_not_requeued_by_a_comment_less_card(self, test_db_session):
        # CARD-A was answered after the customer's last word; CARD-B has no
        # comments at all. Judged per card, whichever was processed last
        # decided the outcome - the case has been answered, so it must stay
        # out of the queue.
        _seed(
            test_db_session,
            [
                _case(),
                _card(jira_card_id="CARD-A"),
                _card(jira_card_id="CARD-B"),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=1)),
                _jira_comment(
                    jira_card_id="CARD-A",
                    last_update_date=CASE_DATE + timedelta(days=2),
                ),
            ],
        )

        assert get_my_queue_cases() == {}

    def test_case_queued_when_no_card_has_answered(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(jira_card_id="CARD-A"),
                _card(jira_card_id="CARD-B"),
                _jira_comment(
                    jira_card_id="CARD-A",
                    last_update_date=CASE_DATE + timedelta(days=1),
                ),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=2)),
            ],
        )

        assert "10000001" in get_my_queue_cases()

    def test_row_uses_the_most_recently_updated_card(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(
                    jira_card_id="CARD-A",
                    status="Backlog",
                    last_update_date=CASE_DATE + timedelta(days=1),
                ),
                _card(
                    jira_card_id="CARD-B",
                    status="In Progress",
                    last_update_date=CASE_DATE + timedelta(days=9),
                ),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=2)),
            ],
        )

        case = get_my_queue_cases()["10000001"]
        assert case["jira_card_id"] == "CARD-B"
        assert case["jira_status"] == "In Progress"

    def test_no_update_mark_on_any_card_excludes(self, test_db_session):
        _seed(
            test_db_session,
            [
                _case(),
                _card(jira_card_id="CARD-A"),
                _card(
                    jira_card_id="CARD-B",
                    no_update_date=CASE_DATE + timedelta(days=5),
                ),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=2)),
            ],
        )

        assert get_my_queue_cases() == {}


class TestGetMyQueueCasesNullStatus:
    def test_case_without_a_status_is_not_dropped(self, test_db_session):
        # `status != 'Closed'` is NULL - and so false - for a NULL status.
        _seed(
            test_db_session,
            [
                _case(status=None),
                _card(),
                _portal_comment(commented_at=CASE_DATE + timedelta(days=2)),
            ],
        )

        assert "10000001" in get_my_queue_cases()
