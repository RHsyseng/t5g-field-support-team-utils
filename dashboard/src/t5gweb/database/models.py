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
