"""SQLAlchemy database models"""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


class Case(Base):
    """SQLAlchemy model for Red Hat support cases

    Represents a support case from the Red Hat Portal with all associated
    metadata. Uses composite primary key of case_number and created_date.
    Establishes relationships with JIRA cards and comments.

    Attributes:
        case_number: Unique case identifier (e.g., '01234567')
        owner: Case owner/engineer name
        severity: Severity level as integer (1-4)
        account: Customer account name
        summary: Case title/summary text
        status: Current status (Open, Waiting, Closed, etc.)
        created_date: Case creation timestamp
        last_update: Last modification timestamp
        description: Full case description text
        product: Product name
        product_version: Product version string
        fe_jira_card: Associated JIRA card identifier (optional)
        jira_cards: Relationship to JiraCard records
        comments: Relationship to Comment records
    """

    __tablename__ = "cases"

    case_number: Mapped[str] = mapped_column(String, primary_key=True, unique=True)
    owner: Mapped[Optional[str]] = mapped_column(String)
    severity: Mapped[Optional[int]] = mapped_column(Integer)
    account: Mapped[Optional[str]] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[Optional[str]] = mapped_column(String)
    created_date: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    last_update: Mapped[Optional[datetime]] = mapped_column(DateTime)
    description: Mapped[Optional[str]] = mapped_column(String)
    product: Mapped[Optional[str]] = mapped_column(String)
    product_version: Mapped[Optional[str]] = mapped_column(String)
    fe_jira_card: Mapped[Optional[str]] = mapped_column(
        String, unique=True, nullable=True
    )

    jira_cards: Mapped[List["JiraCard"]] = relationship(
        "JiraCard", back_populates="case", cascade="all, delete-orphan"
    )
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", back_populates="case", cascade="all, delete-orphan"
    )


class Comment(Base):
    """SQLAlchemy model for case comments

    Represents comments on Red Hat support cases. Links to parent Case via
    composite foreign key on case_number and created_date.

    Attributes:
        id: Auto-incrementing primary key
        case_number: Reference to parent case number
        created_date: Case creation date for foreign key relationship
        author: Comment author name
        comment_text: Full comment text content
        commented_at: Date comment was posted
        case: Relationship to parent Case record
    """

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String, nullable=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )  # Same as in Case

    author: Mapped[str] = mapped_column(String, nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    commented_at: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["case_number", "created_date"],
            ["cases.case_number", "cases.created_date"],
            ondelete="CASCADE",
        ),
    )
    case: Mapped["Case"] = relationship("Case", back_populates="comments")


class JiraCard(Base):
    """SQLAlchemy model for JIRA cards tracking support cases

    Represents JIRA issues created to track Red Hat support cases. Links to
    parent Case via composite foreign key on case_number and created_date.
    Contains card metadata and establishes relationship with card comments.

    Attributes:
        jira_card_id: JIRA issue key (e.g., 'PROJECT-123')
        case_number: Reference to parent case number
        created_date: Case creation date for foreign key relationship
        last_update_date: Last time card was updated
        summary: Card title/summary
        priority: Card priority level
        status: Current card status
        assignee: JIRA username of assignee
        sprint: Sprint name or identifier
        severity: Severity level as integer (1-4)
        case: Relationship to parent Case record
        comments: Relationship to JiraComment records
    """

    __tablename__ = "jira_cards"

    jira_card_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_number: Mapped[str] = mapped_column(String, nullable=False)
    created_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )  # This should match Case.created_date for FK

    # Updated to include the missing fields from cache.py
    # Separate field for Jira issue creation date - temporarily disabled
    # jira_created_date: Mapped[Optional[datetime]] = mapped_column(
    #   DateTime, nullable=True
    # )

    last_update_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    summary: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # Changed from fe_in_charge to assignee
    sprint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # Made nullable since it might not always be available

    __table_args__ = (
        ForeignKeyConstraint(
            ["case_number", "created_date"],
            ["cases.case_number", "cases.created_date"],
            ondelete="CASCADE",
        ),
    )

    case: Mapped["Case"] = relationship("Case", back_populates="jira_cards")
    comments: Mapped[List["JiraComment"]] = relationship(
        "JiraComment", back_populates="jira_card", cascade="all, delete-orphan"
    )


class JiraComment(Base):
    """SQLAlchemy model for JIRA card comments

    Represents comments on JIRA cards. Links to parent JiraCard via foreign
    key on jira_card_id with cascade delete.

    Attributes:
        jira_comment_id: JIRA comment unique identifier
        jira_card_id: Reference to parent JIRA card
        author: Comment author JIRA username
        body: HTML-formatted comment body text
        last_update_date: Last time comment was modified
        jira_card: Relationship to parent JiraCard record
    """

    __tablename__ = "jira_comments"

    jira_comment_id: Mapped[str] = mapped_column(String, primary_key=True)
    jira_card_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("jira_cards.jira_card_id", ondelete="CASCADE"),
        nullable=False,
    )

    author: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    last_update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    jira_card: Mapped["JiraCard"] = relationship("JiraCard", back_populates="comments")
