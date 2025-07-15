import os
from typing import Optional, List
from datetime import datetime, date
from dateutil import parser
# from t5gweb.db import Base
from sqlalchemy import Integer, String, Date, ForeignKey, ForeignKeyConstraint, Text, DateTime, create_engine
from sqlalchemy.orm import relationship, Mapped, mapped_column, sessionmaker, DeclarativeBase, scoped_session

# Database setup

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:secret@postgresql/dashboard")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

# Create tables - this will be called after models are imported
def create_tables():
    Base.metadata.create_all(bind=engine)


# populate postgres data
def populate_postgres_data(cases):
    db = scoped_session(SessionLocal)
    try:
        for case in cases:
            # Parse the creation date to ensure consistent datetime format
            case_created_date = parser.parse(cases[case]["createdate"])

            pg_case = Case(
                case_number=case,
                owner = cases[case]["owner"],
                severity = cases[case]["severity"][0],
                account = cases[case]["account"],
                summary = cases[case]["problem"],
                status = cases[case]["status"],
                created_date = case_created_date,  # Use parsed datetime
                last_update = parser.parse(cases[case]["last_update"]),  # Parse this too
                description = "testadrien",
                product = cases[case]["product"],
                product_version = cases[case]["product_version"],
                )
            qry_object = db.query(Case).where((Case.case_number == case) & (Case.created_date == case_created_date))
            if qry_object.first() is None:
                db.add(pg_case)
            else:
                pg_case = db.merge(pg_case)
            db.commit()
            db.refresh(pg_case)
    finally:
        db.close()

# Dependency injection

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Define database models

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
    fe_jira_card: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

    jira_cards: Mapped[List["JiraCard"]] = relationship("JiraCard", back_populates="case", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="case", cascade="all, delete-orphan")

class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_number: Mapped[str] = mapped_column(String, nullable=False)
    created_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # Same as in Case

    author: Mapped[str] = mapped_column(String, nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    commented_at: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ['case_number', 'created_date'],
            ['cases.case_number', 'cases.created_date'],
            ondelete='CASCADE'
        ),
    )
    case: Mapped["Case"] = relationship("Case", back_populates="comments")

class JiraCard(Base):
    __tablename__ = "jira_cards"

    jira_card_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_number: Mapped[str] = mapped_column(String, nullable=False)
    created_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # This should match Case.created_date for FK

    # Updated to include the missing fields from cache.py
    # jira_created_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # Separate field for Jira issue creation date - temporarily disabled
    last_update_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Changed from fe_in_charge to assignee
    sprint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    severity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Made nullable since it might not always be available

    __table_args__ = (
        ForeignKeyConstraint(
            ['case_number', 'created_date'],
            ['cases.case_number', 'cases.created_date'],
            ondelete='CASCADE'
        ),
    )

    case: Mapped["Case"] = relationship("Case", back_populates="jira_cards")
    comments: Mapped[List["JiraComment"]] = relationship("JiraComment", back_populates="jira_card", cascade="all, delete-orphan")

class JiraComment(Base):
    __tablename__ = "jira_comments"

    jira_comment_id: Mapped[str] = mapped_column(String, primary_key=True)
    jira_card_id: Mapped[str] = mapped_column(String, ForeignKey("jira_cards.jira_card_id", ondelete='CASCADE'), nullable=False)

    author: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    last_update_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    jira_card: Mapped["JiraCard"] = relationship("JiraCard", back_populates="comments")
