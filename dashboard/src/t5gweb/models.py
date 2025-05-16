# models.py - Define database models
from typing import cast
from t5gweb.db import Base  # Import Base from db.py
from sqlalchemy import Column, Integer, String, Date, FetchedValue

class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, nullable=False, autoincrement=True, server_default=FetchedValue())
    case_number = Column(String, primary_key=True, unique=True)
    owner = Column(String)
    severity = Column(Integer)
    account = Column(String)
    summary = Column(String)
    status = Column(String)
    created_date = Column(Date, primary_key=True)
    last_update = Column(Date)
    description = Column(String)
    product = Column(String)
    product_version = Column(String)
    fe_jira_card = Column(String, unique=True)

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_number = Column(String, nullable=False)
    created_date = Column(Date, nullable=False)  # Same as in Case

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

class JiraComment(Base):
    __tablename__ = "jira_comments"

    jira_comment_id = Column(String, primary_key=True)  # Assuming Jira provides a unique ID per comment

    case_number = Column(String, nullable=False)
    created_date = Column(Date, nullable=False)  # Must match the Case's created_date

    author = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ['case_number', 'created_date'],
            ['cases.case_number', 'cases.created_date'],
            ondelete='CASCADE'
        ),
    )

    case = relationship("Case", backref="jira_comments")

