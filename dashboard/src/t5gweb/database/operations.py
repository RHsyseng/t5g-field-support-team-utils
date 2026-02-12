"""Database operations and data loading functions"""

import logging
import re
from datetime import datetime, timezone

from dateutil import parser
from t5gweb.utils import format_comment

from .models import Case, JiraCard, JiraComment
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
            - fields.customfield_10007: Sprint information

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
                # Temporarily disabled
                # jira_issue_created_date = parser.parse(issue.fields.created)
                time_now = datetime.now(timezone.utc)
                jira_card = JiraCard(
                    jira_card_id=issue.key,
                    case_number=case_number,
                    # Use case creation date for FK
                    created_date=case_created_date,
                    # Store Jira issue creation date separately - temporarily disabled
                    # jira_created_date=jira_issue_created_date,
                    last_update_date=time_now,
                    summary=issue.fields.summary,
                    priority=(
                        issue.fields.priority.name if issue.fields.priority else None
                    ),
                    status=issue.fields.status.name,
                    assignee=(
                        issue.fields.assignee.key if issue.fields.assignee else None
                    ),
                    sprint=(
                        str(issue.fields.customfield_10007[0])
                        if hasattr(issue.fields, "customfield_10007")
                        and issue.fields.customfield_10007
                        else None
                    ),
                    severity=severity_int,
                )
                session.add(jira_card)
                card_processed = True
        else:
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
                            author=comment.author.key,
                            body=body,
                            last_update_date=last_comment_update,
                        )
                        session.add(jira_comment)
                    else:
                        # Update existing comment - create a new object and merge it
                        updated_comment = JiraComment(
                            jira_comment_id=comment.id,
                            jira_card_id=issue.key,
                            author=comment.author.key,
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
