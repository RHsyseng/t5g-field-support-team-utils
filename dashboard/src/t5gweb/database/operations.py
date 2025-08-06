"""Database operations and data loading functions"""

import logging
import re
from datetime import datetime, timezone

from dateutil import parser
from sqlalchemy.orm import scoped_session
from t5gweb.utils import format_comment

from .models import Case, JiraCard, JiraComment
from .session import db_config


def load_cases_postgres(cases):
    """Load cases data into PostgreSQL database"""
    db = scoped_session(db_config.SessionLocal)
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
            qry_object = db.query(Case).where(
                (Case.case_number == case) & (Case.created_date == case_created_date)
            )
            if qry_object.first() is None:
                db.add(pg_case)
            else:
                pg_case = db.merge(pg_case)
            db.commit()
            db.refresh(pg_case)
    finally:
        db.close()


def load_jira_cards_postgres(cases, case_number, issue):
    """Load Jira cards and comments into PostgreSQL database"""
    # Process each card with its own database connection
    db = scoped_session(db_config.SessionLocal)
    card_processed = False
    card_comments = []  # Initialize card_comments for all code paths

    try:
        # Ensure JiraCard exists or create it
        jira_card = db.query(JiraCard).filter_by(jira_card_id=issue.key).first()

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
                db.query(Case)
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
                db.add(jira_card)
                db.commit()
                db.refresh(jira_card)
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
                        db.query(JiraComment)
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
                        db.add(jira_comment)
                    else:
                        # Update existing comment - create a new object and merge it
                        updated_comment = JiraComment(
                            jira_comment_id=comment.id,
                            jira_card_id=issue.key,
                            author=comment.author.key,
                            body=body,
                            last_update_date=parser.parse(comment.updated),
                        )
                        db.merge(updated_comment)

                    db.commit()
                except Exception as e:
                    logging.warning("Issue storing comment into database: %s", e)
                    db.rollback()

    finally:
        # Always close the database connection for this card
        db.close()

    return card_processed, card_comments  # Return both values
