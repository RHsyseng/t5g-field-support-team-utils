# models.py - Define database models
from typing import cast
from t5gweb.db import Base  # Import Base from db.py
from sqlalchemy import Column, Integer, String, Date, FetchedValue, ForeignKey, ForeignKeyConstraint, Text, DateTime
from sqlalchemy.orm import relationship

class Case(Base):
    __tablename__ = "cases"

    case_number = Column(String, primary_key=True, unique=True)
    owner = Column(String)
    severity = Column(Integer)
    account = Column(String)
    summary = Column(String)
    status = Column(String)
    created_date = Column(DateTime, primary_key=True)
    last_update = Column(DateTime)
    description = Column(String)
    product = Column(String)
    product_version = Column(String)
    fe_jira_card = Column(String, unique=True, nullable=True)

    jira_cards = relationship("JiraCard", back_populates="case", cascade="all, delete-orphan")

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_number = Column(String, nullable=False)
    created_date = Column(DateTime, nullable=False)  # Same as in Case

    author = Column(String, nullable=False)
    comment_text = Column(Text, nullable=False)
    commented_at = Column(Date, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ['case_number', 'created_date'],
            ['cases.case_number', 'cases.created_date'],
            ondelete='CASCADE'
        ),
    )
    case = relationship("Case", backref="comments")

class JiraCard(Base):
    __tablename__ = "jira_cards"

    jira_card_id = Column(String, primary_key=True)
    case_number = Column(String, nullable=False)
    created_date = Column(DateTime, nullable=False)  # This should match Case.created_date for FK

    # Updated to include the missing fields from cache.py
    # jira_created_date = Column(DateTime, nullable=True)  # Separate field for Jira issue creation date - temporarily disabled
    last_update_date = Column(DateTime, nullable=True)
    summary = Column(String, nullable=False)
    priority = Column(String, nullable=True)
    status = Column(String, nullable=True)
    assignee = Column(String, nullable=True)  # Changed from fe_in_charge to assignee
    sprint = Column(String, nullable=True)
    severity = Column(Integer, nullable=True)  # Made nullable since it might not always be available

    __table_args__ = (
        ForeignKeyConstraint(
            ['case_number', 'created_date'],
            ['cases.case_number', 'cases.created_date'],
            ondelete='CASCADE'
        ),
    )

    case = relationship("Case", back_populates="jira_cards")
    comments = relationship("JiraComment", back_populates="jira_card", cascade="all, delete-orphan")

class JiraComment(Base):
    __tablename__ = "jira_comments"

    jira_comment_id = Column(String, primary_key=True)
    jira_card_id = Column(String, ForeignKey("jira_cards.jira_card_id", ondelete='CASCADE'), nullable=False)

    author = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    last_update_date = Column(DateTime, nullable=False)

    jira_card = relationship("JiraCard", back_populates="comments")
