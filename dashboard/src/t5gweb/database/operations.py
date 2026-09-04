"""Database operations and data loading functions"""

import logging
import re
from datetime import datetime, timezone

from dateutil import parser

from t5gweb.utils import format_comment

from .models import Case, Comment, JiraCard, JiraComment
from .session import db_config


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

        for api_comment in api_comments:
            author = api_comment.get("createdBy", "unknown")
            body = api_comment.get("commentBody", "")
            comment_type = api_comment.get("createdByType")
            commented_at_str = api_comment.get("createdDate")
            if not commented_at_str:
                continue

            commented_at = parser.parse(commented_at_str)

            existing = (
                session.query(Comment)
                .filter_by(
                    case_number=case_number,
                    author=author,
                    commented_at=commented_at,
                )
                .first()
            )
            if existing is None:
                comment = Comment(
                    case_number=case_number,
                    created_date=case_created_date,
                    author=author,
                    comment_type=comment_type,
                    comment_text=body,
                    commented_at=commented_at,
                )
                session.add(comment)
            elif existing.comment_type is None and comment_type:
                existing.comment_type = comment_type

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

    try:
        # Ensure JiraCard exists or create it
        jira_card = session.query(JiraCard).filter_by(jira_card_id=issue.key).first()

        if jira_card is None:
            # Extract severity as integer from cases data
            severity_int = None
            if case_number in cases and "severity" in cases[case_number]:
                severity_match = re.search(r"\d+", cases[case_number]["severity"])
                if severity_match:
                    severity_int = int(severity_match.group())

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

                sprint_value = None
                if (
                    hasattr(issue.fields, "customfield_10020")
                    and issue.fields.customfield_10020
                ):
                    sprint_obj = issue.fields.customfield_10020[-1]
                    raw_sprint_name = getattr(sprint_obj, "name", str(sprint_obj))
                    match = re.search(r"Sprint\s+(\d+)", raw_sprint_name)
                    if match:
                        sprint_value = f"T5GFE Sprint {match.group(1)}"
                    else:
                        sprint_value = raw_sprint_name

                jira_card = JiraCard(
                    jira_card_id=issue.key,
                    case_number=case_number,
                    created_date=case_created_date,
                    last_update_date=(
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
                    sprint=sprint_value,
                    severity=severity_int,
                )
                session.add(jira_card)
                card_processed = True
        else:
            time_now = datetime.now(timezone.utc)

            sprint_value = None
            if (
                hasattr(issue.fields, "customfield_10020")
                and issue.fields.customfield_10020
            ):
                sprint_obj = issue.fields.customfield_10020[-1]
                raw_sprint_name = getattr(sprint_obj, "name", str(sprint_obj))
                match = re.search(r"Sprint\s+(\d+)", raw_sprint_name)
                if match:
                    sprint_value = f"T5GFE Sprint {match.group(1)}"
                else:
                    sprint_value = raw_sprint_name

            jira_card.last_update_date = (
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
            jira_card.sprint = sprint_value

            session.merge(jira_card)
            card_processed = True

        # Only process comments if the card was successfully processed
        if card_processed:
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
                        last_comment_update = parser.parse(comment.updated)

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
                            last_update_date=parser.parse(comment.updated),
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


def get_my_queue_cases(active_sprint_name=None, engineer_filter=None):
    """Query cases in the engineer's queue that need attention.

    Filters cases based on:
    1. Portal status is not "Closed"
    2. Has an associated JIRA card
    3. Most recent portal comment is newer than most recent JIRA comment
    4. Optionally filtered by sprint and/or engineer

    Args:
        active_sprint_name: Name/ID of the sprint to filter by (optional)
        engineer_filter: Engineer name to filter by (optional)

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
                    'portal_comments': [
                        {'author': str, 'date': datetime, 'body': str}
                    ],
                    'jira_comments': [
                        {'author': str, 'updated': datetime, 'body': str}
                    ],
                    'most_recent_jira_comment': {
                        'author': str, 'updated': str, 'body': str
                    }
                }
            }
    """
    session = db_config.SessionLocal()
    my_queue_cases = {}

    try:
        # Query cases with JIRA cards - filter by sprint if provided
        cases_query = (
            session.query(Case, JiraCard)
            .join(
                JiraCard,
                (Case.case_number == JiraCard.case_number)
                & (Case.created_date == JiraCard.created_date),
            )
            .filter(Case.status != "Closed")
        )

        # Apply sprint filter if provided
        if active_sprint_name:
            cases_query = cases_query.filter(JiraCard.sprint == active_sprint_name)
            sprint_msg = f"sprint '{active_sprint_name}'"
        else:
            sprint_msg = "all sprints"

        # Apply engineer filter if provided
        if engineer_filter:
            cases_query = cases_query.filter(JiraCard.assignee == engineer_filter)
            engineer_msg = f", engineer '{engineer_filter}'"
        else:
            engineer_msg = ""

        all_cases = cases_query.all()
        logging.warning(
            "Found %d total cases (not closed, %s%s)",
            len(all_cases),
            sprint_msg,
            engineer_msg,
        )

        filtered_count = 0
        no_jira_comments = 0
        jira_newer = 0
        no_portal_comments = 0
        included_no_jira = 0
        no_update_marked = 0

        for case, jira_card in all_cases:
            # Load portal comments (newest first)
            portal_comments = (
                session.query(Comment)
                .filter(Comment.case_number == case.case_number)
                .filter(Comment.created_date == case.created_date)
                .order_by(Comment.commented_at.desc())
                .all()
            )

            # Load JIRA comments (newest first)
            jira_comments = (
                session.query(JiraComment)
                .filter(JiraComment.jira_card_id == jira_card.jira_card_id)
                .order_by(JiraComment.last_update_date.desc())
                .all()
            )

            # Track cases without portal comments
            if not portal_comments:
                no_portal_comments += 1

            # If no JIRA comments exist, INCLUDE the case (Vue behavior line 50)
            if not jira_comments:
                no_jira_comments += 1
                included_no_jira += 1
                # Fall through to add this case
            else:
                # Get most recent comment dates
                jira_comment_last_update = jira_comments[0].last_update_date
                portal_comment_last_update = (
                    portal_comments[0].commented_at
                    if portal_comments
                    else datetime(1970, 1, 1, tzinfo=timezone.utc)
                )

                # Ensure both datetimes are timezone-aware for comparison
                if jira_comment_last_update.tzinfo is None:
                    jira_comment_last_update = jira_comment_last_update.replace(
                        tzinfo=timezone.utc
                    )
                if portal_comment_last_update.tzinfo is None:
                    portal_comment_last_update = portal_comment_last_update.replace(
                        tzinfo=timezone.utc
                    )

                # Exclude if the case was marked "no update needed" more
                # recently than the newest portal comment
                # (Vue: if noUpdate >= portal, exclude)
                no_update_date = jira_card.no_update_date
                if no_update_date is not None:
                    if no_update_date.tzinfo is None:
                        no_update_date = no_update_date.replace(tzinfo=timezone.utc)
                    if no_update_date >= portal_comment_last_update:
                        no_update_marked += 1
                        continue

                # Only include if portal comment is newer than JIRA comment
                # (Vue line 41: if jira >= portal, exclude)
                if jira_comment_last_update >= portal_comment_last_update:
                    jira_newer += 1
                    continue

            filtered_count += 1

            # Format portal comments
            formatted_portal_comments = [
                {
                    "author": comment.author,
                    "date": comment.commented_at.isoformat(),
                    "body": comment.comment_text,
                }
                for comment in portal_comments
            ]

            # Format JIRA comments
            formatted_jira_comments = [
                {
                    "author": comment.author,
                    "updated": comment.last_update_date.isoformat(),
                    "body": comment.body,
                }
                for comment in jira_comments
            ]

            # Build result structure
            my_queue_cases[case.case_number] = {
                "case_number": case.case_number,
                "severity": case.severity,
                "summary": case.summary,
                "field_engineer": jira_card.assignee,
                "portal_status": case.status,
                "jira_status": jira_card.status,
                "portal_comments": formatted_portal_comments,
                "jira_comments": formatted_jira_comments,
                "most_recent_jira_comment": (
                    formatted_jira_comments[0] if formatted_jira_comments else None
                ),
            }

        logging.warning(
            "Filtering results: %d cases need attention " "out of %d total",
            filtered_count,
            len(all_cases),
        )
        logging.warning(
            "  - No JIRA comments (included): %d",
            included_no_jira,
        )
        logging.warning(
            "  - No portal comments: %d",
            no_portal_comments,
        )
        logging.warning(
            "  - JIRA comment newer (excluded): %d",
            jira_newer,
        )
        logging.warning(
            "  - Marked no update needed (excluded): %d",
            no_update_marked,
        )

        from collections import Counter

        engineer_counts = Counter(
            case_data["field_engineer"] for case_data in my_queue_cases.values()
        )
        logging.warning("Cases by engineer: %s", dict(engineer_counts))

    except Exception as e:
        logging.error(f"Failed to get my queue cases: {e}")
        session.rollback()
    finally:
        session.close()

    return my_queue_cases
