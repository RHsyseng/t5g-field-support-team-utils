"""Database operations and data loading functions"""

import logging
import re
from datetime import datetime, timezone

from dateutil import parser
from sqlalchemy import func, or_

from t5gweb.utils import format_comment, severity_text

from .models import Case, Comment, JiraCard, JiraComment
from .session import db_config


class PgError(Exception):
    """Raised when a PostgreSQL operation fails and the caller must decide how
    to recover (e.g. fall back to an empty result)."""


# JIRA reports a sprint either as an object with a ``name`` or, on older
# instances, as a serialized blob: ``com.atlassian...@1[id=5,name=Foo Sprint
# 42,state=ACTIVE,...]``. Pull the real name out of the blob rather than
# rebuilding it from the sprint number, which would relabel every board's
# sprints with one hardcoded prefix.
_SPRINT_NAME_RE = re.compile(r"name=([^,\]]+)")


def _sprint_name(issue):
    """Return the name of the card's current sprint, or None if it has none."""
    sprints = getattr(issue.fields, "customfield_10020", None)
    if not sprints:
        return None

    sprint_obj = sprints[-1]
    name = getattr(sprint_obj, "name", None)
    if name:
        return name

    blob = str(sprint_obj)
    match = _SPRINT_NAME_RE.search(blob)
    return match.group(1) if match else blob


def _utc_naive(value):
    """Normalize a datetime to naive UTC for storage.

    ``JiraCard.last_update_date`` / ``JiraComment.last_update_date`` are
    ``TIMESTAMP WITHOUT TIME ZONE``, so psycopg stores the wall clock and drops
    the offset. A JIRA instance reporting e.g. +02:00 would therefore be stored
    two hours ahead of the UTC portal timestamps it is later compared against
    (``get_my_queue_cases`` re-labels these naive values as UTC). Convert to UTC
    first so that re-labelling is true.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def load_cases_postgres(cases):
    """Load or update cases data in PostgreSQL database

    Inserts new cases or updates existing cases in the database. Uses case
    number and creation date as composite primary key. Automatically commits
    changes and handles rollback on errors.

    Args:
        cases: Dictionary of case data keyed by case number, each containing:
            - owner: Case owner name
            - severity: Severity level string (e.g., '1 (Urgent)')
            - account: Customer account name
            - problem: Case summary/title
            - status: Current case status
            - createdate: Case creation timestamp string
            - last_update: Last modified timestamp string
            - closeddate: Close timestamp string (optional; set on closed cases)
            - description: Case description text
            - product: Product name
            - product_version: Product version

    Returns:
        None. Data is committed to PostgreSQL database.
    """
    logging.warning(f"Starting load_cases_postgres with {len(cases)} cases")
    logging.warning(f"Execution context: {db_config.get_execution_context()}")
    session = db_config.SessionLocal()
    logging.warning("Database session created")
    try:
        for case in cases:
            # Parse the creation date to ensure consistent datetime format
            case_created_date = parser.parse(cases[case]["createdate"])

            pg_case = Case(
                case_number=case,
                owner=cases[case]["owner"],
                severity=cases[case]["severity"][0],
                account=cases[case]["account"],
                summary=cases[case]["problem"],
                status=cases[case]["status"],
                created_date=case_created_date,  # Use parsed datetime
                last_update=parser.parse(cases[case]["last_update"]),  # Parse this too
                closed_date=(
                    parser.parse(cases[case]["closeddate"])
                    if cases[case].get("closeddate")
                    else None
                ),
                description=cases[case]["description"],
                product=cases[case]["product"],
                product_version=cases[case]["product_version"],
            )
            qry_object = session.query(Case).where(
                (Case.case_number == case) & (Case.created_date == case_created_date)
            )
            if qry_object.first() is None:
                session.add(pg_case)
            else:
                pg_case = session.merge(pg_case)
        session.commit()
        logging.warning("Database commit completed successfully")
    except Exception as e:
        session.rollback()
        logging.error(f"Failed to load cases: {e}")
    finally:
        session.close()
        logging.warning("Loaded cases to Postgres")


def load_open_cases_postgres():
    """Return full case projections for not-yet-closed cases known to PostgreSQL.

    Unlike the Redis ``cases`` cache (overwritten wholesale on every sync), the
    PostgreSQL ``cases`` table is never bulk-cleared, so it is the durable source
    of truth for every case the dashboard has tracked. ``merge_closed_cases``
    uses this as its universe of previously-known cases: a case that dropped out
    of both the open saved-search and the Redis cache still has a row here and is
    carried forward (and re-verified) from its stored projection - no rebuild
    from GraphQL needed.

    Cases already marked ``"Closed"`` are excluded so the universe (and the
    downstream closure re-verification) stays bounded to still-open cases.

    Returns:
        dict: case number -> projection dict in the same shape ``get_cases``
            builds (``owner``, ``severity``, ``account``, ``problem``,
            ``status``, ``createdate``, ``last_update``, ``closeddate``,
            ``description``, ``product``, ``product_version``).

    Raises:
        PgError: on any database error, so the caller can decide how to recover
            (``merge_closed_cases`` falls back to the Redis universe alone).
    """

    def _ts(value):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None

    session = db_config.SessionLocal()
    try:
        # NULL-safe: in SQL `status != 'Closed'` is NULL (and so filtered out)
        # for a row with no status, which would hide the case entirely.
        rows = (
            session.query(Case)
            .filter(or_(Case.status.is_(None), Case.status != "Closed"))
            .all()
        )
        return {
            row.case_number: {
                "owner": row.owner,
                # Re-expand "3" to "3 (Medium)": the column holds only the
                # number, but every reader of a projection expects the portal
                # form and breaks on a letter-less severity.
                "severity": severity_text(row.severity),
                "account": row.account,
                "problem": row.summary,
                "status": row.status,
                "createdate": _ts(row.created_date),
                "last_update": _ts(row.last_update),
                "closeddate": _ts(row.closed_date),
                "description": row.description,
                "product": row.product,
                "product_version": row.product_version,
            }
            for row in rows
        }
    except Exception as e:
        logging.error(f"Failed to read open cases: {e}")
        raise PgError(f"Failed to read open cases: {e}") from e
    finally:
        session.close()


def comment_watermarks_postgres(case_numbers):
    """Return the newest stored portal-comment timestamp per case.

    Lets the comment sync ask the API only for what it does not already hold:
    the UIAPI comment object is queried wholesale (one page per 100 comments),
    so re-reading complete histories every run costs hundreds of round-trips
    against an API whose practical limit is WAF throttling.

    Args:
        case_numbers: case numbers to look up.

    Returns:
        dict: case number -> newest ``commented_at`` (naive UTC, as stored).
            Cases with no stored comments are absent.

    Raises:
        PgError: on any database error, so the caller can fall back to a full
            fetch rather than silently skipping comments.
    """
    if not case_numbers:
        return {}

    session = db_config.SessionLocal()
    try:
        rows = (
            session.query(Comment.case_number, func.max(Comment.commented_at))
            .filter(Comment.case_number.in_(list(case_numbers)))
            .group_by(Comment.case_number)
            .all()
        )
        return {case_number: newest for case_number, newest in rows if newest}
    except Exception as e:
        logging.error(f"Failed to read comment watermarks: {e}")
        raise PgError(f"Failed to read comment watermarks: {e}") from e
    finally:
        session.close()


def load_comments_postgres(case_number, case_created_date, api_comments):
    """Load or update Portal case comments in PostgreSQL.

    Args:
        case_number: The case number these comments belong to.
        case_created_date: Parsed datetime of the case's creation date (for the
            composite FK to the cases table).
        api_comments: List of comment dicts from the Portal API, each containing
            at minimum 'createdBy', 'commentBody', and 'createdDate'.
    """
    if not api_comments:
        return

    session = db_config.SessionLocal()
    try:
        existing_case = (
            session.query(Case)
            .filter_by(case_number=case_number, created_date=case_created_date)
            .first()
        )
        if existing_case is None:
            logging.warning(
                "Cannot load comments for %s - case not found in database",
                case_number,
            )
            return

        # The de-dup query below cannot see rows added earlier in this same
        # loop (the session is autoflush=False), so a batch that carries the
        # same comment twice - e.g. a sweep that re-read a page - would insert
        # it twice. Track what this batch has already handled.
        seen = set()

        for api_comment in api_comments:
            author = api_comment.get("createdBy", "unknown")
            body = api_comment.get("commentBody", "")
            comment_type = api_comment.get("createdByType")
            # None means the source could not tell us (uiapi_comment_to_dict
            # reports unknown visibility as None); store NULL rather than a
            # guess, which readers render as public.
            is_public = api_comment.get("isPublic")
            if is_public is not None:
                is_public = bool(is_public)
            commented_at_str = api_comment.get("createdDate")
            if not commented_at_str:
                continue

            # The portal sends UTC ("...Z"); the column is naive, so without
            # this the value lands in whatever the session TimeZone is. That
            # skews the comparison against JIRA timestamps in
            # get_my_queue_cases, and comment_watermarks_postgres would send a
            # shifted floor back to the API - with a positive offset, comments
            # in the offset window would never be fetched again.
            commented_at = _utc_naive(parser.parse(commented_at_str))

            if (author, commented_at, body) in seen:
                continue
            seen.add((author, commented_at, body))

            # Author and timestamp alone do not identify a comment: automation
            # accounts post several distinct comments within the same second,
            # and matching on them would merge those into one. Prefer the row
            # with the same body; fall back to the single row that differs only
            # in text, which is the same comment edited (or re-rendered in the
            # newer Markdown format).
            same_timestamp = (
                session.query(Comment)
                .filter_by(
                    case_number=case_number,
                    author=author,
                    commented_at=commented_at,
                )
                .all()
            )
            existing = next(
                (row for row in same_timestamp if row.comment_text == body), None
            )
            if existing is None and len(same_timestamp) == 1:
                existing = same_timestamp[0]

            if existing is None:
                comment = Comment(
                    case_number=case_number,
                    created_date=case_created_date,
                    author=author,
                    comment_type=comment_type,
                    comment_text=body,
                    commented_at=commented_at,
                    is_public=is_public,
                )
                session.add(comment)
            else:
                # The API is authoritative, so refresh the stored row on every
                # sync: one written before these columns existed (NULL) gets
                # backfilled, one written from a wrong/guessed value is
                # corrected instead of staying wrong forever, and a body stored
                # in an older format (raw HTML, before the Markdown conversion)
                # is rewritten. A value the API cannot supply (None) never
                # overwrites a known one.
                if comment_type:
                    existing.comment_type = comment_type
                if is_public is not None:
                    existing.is_public = is_public
                if body:
                    existing.comment_text = body

        session.commit()
    except Exception as e:
        session.rollback()
        logging.error("Failed to load comments for case %s: %s", case_number, e)
    finally:
        session.close()


def load_jira_card_postgres(cases, case_number, issue):
    """Load or update a JIRA card and its comments in PostgreSQL database

    Creates or updates a JIRA card record and all its associated comments in
    the database. Establishes foreign key relationship with the parent case
    using case_number and creation_date composite key. Each call uses its own
    database session for isolation.

    Args:
        cases: Dictionary of all case data keyed by case number
        case_number: Case number that this JIRA card is associated with
        issue: JIRA issue object containing card details including:
            - key: JIRA card identifier
            - fields.summary: Card title
            - fields.priority: Priority object
            - fields.status: Status object
            - fields.assignee: Assignee object
            - fields.comment.comments: List of comment objects
            - fields.customfield_10020: Sprint information
    Returns:
        tuple: (card_processed: bool, card_comments: list) where card_processed
            indicates if card was successfully stored and card_comments contains
            list of (body, timestamp) tuples for all comments
    """
    # Process each card with its own database connection
    session = db_config.SessionLocal()  # Fix: Add () to create instance
    card_processed = False
    card_comments = []  # Initialize card_comments for all code paths

    # Extract severity as integer from cases data
    severity_int = None
    if case_number in cases and "severity" in cases[case_number]:
        severity_match = re.search(r"\d+", str(cases[case_number]["severity"]))
        if severity_match:
            severity_int = int(severity_match.group())

    try:
        # Ensure JiraCard exists or create it
        jira_card = session.query(JiraCard).filter_by(jira_card_id=issue.key).first()

        if jira_card is None:
            # Use the case's creation date for the foreign key relationship
            case_created_date = parser.parse(cases[case_number]["createdate"])

            # Verify that the corresponding case exists in the database
            existing_case = (
                session.query(Case)
                .filter_by(case_number=case_number, created_date=case_created_date)
                .first()
            )

            if existing_case is None:
                logging.warning(
                    "Cannot create JiraCard for %s - "
                    "corresponding case not found in database",
                    case_number,
                )
                # Skip this card - will be handled in finally block
                card_processed = False
            else:
                time_now = datetime.now(timezone.utc)

                sprint_value = _sprint_name(issue)

                jira_card = JiraCard(
                    jira_card_id=issue.key,
                    case_number=case_number,
                    created_date=case_created_date,
                    last_update_date=_utc_naive(
                        parser.parse(issue.fields.updated)
                        if getattr(issue.fields, "updated", None)
                        else time_now
                    ),
                    summary=issue.fields.summary,
                    priority=(
                        issue.fields.priority.name if issue.fields.priority else None
                    ),
                    status=issue.fields.status.name,
                    assignee=(
                        issue.fields.assignee.displayName
                        if issue.fields.assignee
                        else None
                    ),
                    assignee_email=(
                        getattr(issue.fields.assignee, "emailAddress", None)
                        if issue.fields.assignee
                        else None
                    ),
                    sprint=sprint_value,
                    severity=severity_int,
                )
                session.add(jira_card)
                card_processed = True
        else:
            time_now = datetime.now(timezone.utc)

            sprint_value = _sprint_name(issue)

            jira_card.last_update_date = _utc_naive(
                parser.parse(issue.fields.updated)
                if getattr(issue.fields, "updated", None)
                else time_now
            )
            jira_card.summary = issue.fields.summary
            jira_card.priority = (
                issue.fields.priority.name if issue.fields.priority else None
            )
            jira_card.status = issue.fields.status.name
            jira_card.assignee = (
                issue.fields.assignee.displayName if issue.fields.assignee else None
            )
            jira_card.assignee_email = (
                getattr(issue.fields.assignee, "emailAddress", None)
                if issue.fields.assignee
                else None
            )
            jira_card.sprint = sprint_value
            # Refresh the severity too: a case whose severity is raised would
            # otherwise keep the value it had when the card was first stored.
            if severity_int is not None:
                jira_card.severity = severity_int

            session.merge(jira_card)
            card_processed = True

        # Only process comments if the card was successfully processed
        if card_processed:
            # Commit the card before touching comments. A comment that fails to
            # store rolls the session back and continues; with the card still
            # pending, that rollback silently discarded its field updates
            # (assignee_email above all) while still reporting success - and a
            # card with no assignee_email never shows up in anyone's queue.
            session.commit()

            # Process comments in batches to avoid holding transaction too long
            comments = issue.fields.comment.comments

            for comment in comments:
                body = format_comment(comment)
                tstamp = comment.updated
                card_comments.append((body, tstamp))

                # Store comment in PostgreSQL database
                try:
                    existing_comment = (
                        session.query(JiraComment)
                        .filter_by(jira_comment_id=comment.id)
                        .first()
                    )

                    if existing_comment is None:
                        # Parse the comment timestamp
                        last_comment_update = _utc_naive(parser.parse(comment.updated))

                        jira_comment = JiraComment(
                            jira_comment_id=comment.id,
                            jira_card_id=issue.key,
                            author=comment.author.displayName,
                            body=body,
                            last_update_date=last_comment_update,
                        )
                        session.add(jira_comment)
                    else:
                        # Update existing comment - create a new object and merge it
                        updated_comment = JiraComment(
                            jira_comment_id=comment.id,
                            jira_card_id=issue.key,
                            author=comment.author.displayName,
                            body=body,
                            last_update_date=_utc_naive(parser.parse(comment.updated)),
                        )
                        session.merge(updated_comment)

                except Exception as e:
                    logging.warning("Issue storing comment into database: %s", e)
                    session.rollback()
                    continue

        # Single commit for all operations
        session.commit()

    except Exception as e:
        session.rollback()
        logging.error(f"Failed to load Jira card {issue.key}: {e}")
        raise
    finally:
        # Always close the database connection for this card
        session.close()

    return card_processed, card_comments  # Return both values


def get_my_queue_cases(active_sprint_name=None, engineer_email=None):
    """Query cases in the engineer's queue that need attention.

    Filters cases based on:
    1. Portal status is not "Closed"
    2. Has an associated JIRA card
    3. Most recent portal comment is newer than most recent JIRA comment
    4. Optionally filtered by sprint and/or engineer

    Args:
        active_sprint_name: Name/ID of the sprint to filter by (optional)
        engineer_email: Engineer email address to match against the JIRA
            assignee email (optional)

    Returns:
        dict: Cases needing attention, keyed by case_number, with structure:
            {
                case_number: {
                    'case_number': str,
                    'severity': int,
                    'summary': str,
                    'field_engineer': str,
                    'portal_status': str,
                    'jira_status': str,
                    'jira_card_id': str,
                    'most_recent_jira_comment': {
                        'author': str, 'updated': str, 'body': str
                    }
                }
            }

        The comment bodies themselves are deliberately not included: the table
        only renders the newest JIRA comment, and the expanded row fetches the
        full history on demand from ``/api/my-queue/case/<n>/comments``. Loading
        every comment of every queued case here just to discard it made the page
        render read thousands of rows it never showed.
    """
    session = db_config.SessionLocal()
    my_queue_cases = {}

    try:
        # Query cases with JIRA cards - filter by sprint if provided
        cases_query = (
            session.query(Case, JiraCard).join(
                JiraCard,
                (Case.case_number == JiraCard.case_number)
                & (Case.created_date == JiraCard.created_date),
            )
            # NULL-safe (see load_open_cases_postgres): a case with no status
            # must not vanish from the queue.
            .filter(or_(Case.status.is_(None), Case.status != "Closed"))
            # A case can carry several cards; the last one processed wins the
            # row, so order the join to make that choice reproducible between
            # runs instead of leaving it to the planner.
            .order_by(Case.case_number, JiraCard.jira_card_id)
        )

        # Apply sprint filter if provided
        if active_sprint_name:
            cases_query = cases_query.filter(JiraCard.sprint == active_sprint_name)
            sprint_msg = f"sprint '{active_sprint_name}'"
        else:
            sprint_msg = "all sprints"

        # Apply engineer filter if provided (match on the JIRA assignee email).
        # SAML and JIRA disagree on the case of an address often enough
        # (Firstname.Lastname@ vs firstname.lastname@) that an exact match
        # silently returns an empty queue, so compare case-insensitively.
        if engineer_email is not None:
            cases_query = cases_query.filter(
                func.lower(JiraCard.assignee_email) == engineer_email.lower()
            )
            engineer_msg = f", engineer '{engineer_email}'"
        else:
            engineer_msg = ""

        all_cases = cases_query.all()
        logging.debug(
            "Found %d total cases (not closed, %s%s)",
            len(all_cases),
            sprint_msg,
            engineer_msg,
        )
        if engineer_email is not None and not all_cases:
            # An empty queue is indistinguishable from a bad match, so say which
            # address found nothing rather than rendering a blank table silently.
            logging.warning("no JIRA cards matched assignee email '%s'", engineer_email)

        filtered_count = 0
        no_jira_comments = 0
        jira_newer = 0
        no_portal_comments = 0
        included_no_jira = 0
        no_update_marked = 0

        # Judge a case once, across every card tracking it. Iterating the join
        # row by row let a later card re-add a case an earlier one had excluded
        # (and vice versa), so whether an answered case appeared came down to
        # the order the cards came back in.
        cards_by_case = {}
        for case, jira_card in all_cases:
            cards_by_case.setdefault(case.case_number, (case, []))[1].append(jira_card)

        for case, jira_cards in cards_by_case.values():
            # The card the row is built from: the most recently updated one, so
            # a case with several cards shows its live conversation.
            jira_card = max(
                jira_cards,
                key=lambda card: (
                    card.last_update_date is not None,
                    card.last_update_date,
                    card.jira_card_id,
                ),
            )

            # Newest portal comment of ANY author type, which is what the case
            # is waiting on. Restricting this to the customer looks right on
            # paper - "has the customer spoken since we answered" - but the
            # Red Hat associate who owns the case chases the telco engineer on
            # the portal ("we are still waiting for an update on this case"),
            # and those chases are exactly the work this queue exists to
            # surface: measured against the live data, filtering them out hid
            # 9 of 29 cases and not one of them was the engineer's own reply.
            newest_portal_comment = (
                session.query(Comment)
                .filter(Comment.case_number == case.case_number)
                .filter(Comment.created_date == case.created_date)
                .order_by(Comment.commented_at.desc())
                .first()
            )

            # Newest JIRA comment across every card tracking the case: an
            # answer on any of them is still an answer.
            newest_jira_comment = (
                session.query(JiraComment)
                .filter(
                    JiraComment.jira_card_id.in_(
                        [card.jira_card_id for card in jira_cards]
                    )
                )
                .order_by(JiraComment.last_update_date.desc())
                .first()
            )

            # Track cases without portal comments
            if newest_portal_comment is None:
                no_portal_comments += 1

            # Most recent portal comment date (tz-aware), epoch if none exist
            portal_comment_last_update = (
                newest_portal_comment.commented_at
                if newest_portal_comment
                else datetime(1970, 1, 1, tzinfo=timezone.utc)
            )
            if portal_comment_last_update.tzinfo is None:
                portal_comment_last_update = portal_comment_last_update.replace(
                    tzinfo=timezone.utc
                )

            # Exclude if the case was marked "no update needed" more recently
            # than the newest portal comment. Checked up front so it applies
            # whether or not the card has JIRA comments. The latest mark on any
            # of the case's cards counts.
            # (Vue: if noUpdate >= portal, exclude)
            marks = [
                card.no_update_date
                for card in jira_cards
                if card.no_update_date is not None
            ]
            no_update_date = max(marks) if marks else None
            if no_update_date is not None:
                if no_update_date.tzinfo is None:
                    no_update_date = no_update_date.replace(tzinfo=timezone.utc)
                if no_update_date >= portal_comment_last_update:
                    no_update_marked += 1
                    continue

            # If no JIRA comments exist, INCLUDE the case (Vue behavior line 50)
            if newest_jira_comment is None:
                no_jira_comments += 1
                included_no_jira += 1
                # Fall through to add this case
            else:
                # Get most recent JIRA comment date (tz-aware)
                jira_comment_last_update = newest_jira_comment.last_update_date
                if jira_comment_last_update.tzinfo is None:
                    jira_comment_last_update = jira_comment_last_update.replace(
                        tzinfo=timezone.utc
                    )

                # Only include if portal comment is newer than JIRA comment
                # (Vue line 41: if jira >= portal, exclude)
                if jira_comment_last_update >= portal_comment_last_update:
                    jira_newer += 1
                    continue

            filtered_count += 1

            # Build result structure. Only the newest JIRA comment is carried:
            # the full histories are served by the comments endpoint when a row
            # is expanded.
            my_queue_cases[case.case_number] = {
                "case_number": case.case_number,
                "severity": case.severity,
                "summary": case.summary,
                "field_engineer": jira_card.assignee,
                "portal_status": case.status,
                "jira_status": jira_card.status,
                "jira_card_id": jira_card.jira_card_id,
                "most_recent_jira_comment": (
                    {
                        "author": newest_jira_comment.author,
                        "updated": newest_jira_comment.last_update_date.isoformat(),
                        "body": newest_jira_comment.body,
                    }
                    if newest_jira_comment
                    else None
                ),
            }

        logging.debug(
            "Filtering results: %d cases need attention " "out of %d total",
            filtered_count,
            len(all_cases),
        )
        logging.debug("  - No JIRA comments (included): %d", included_no_jira)
        logging.debug("  - No portal comments: %d", no_portal_comments)
        logging.debug("  - JIRA comment newer (excluded): %d", jira_newer)
        logging.debug("  - Marked no update needed (excluded): %d", no_update_marked)

    except Exception as e:
        logging.error(f"Failed to get my queue cases: {e}")
        session.rollback()
    finally:
        session.close()

    return my_queue_cases
