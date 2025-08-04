"""Database module for t5gweb

This module provides database functionality including:
- Database models (Case, Comment, JiraCard, JiraComment)
- Session management (engine, SessionLocal, Base)
- Database operations (load_cases_postgres, load_jira_cards_postgres)
- Utility functions (get_db, create_postgres_tables)
"""

# Import database models
from .models import Case, Comment, JiraCard, JiraComment
# Import database operations
from .operations import load_cases_postgres, load_jira_cards_postgres
# Import session management components
from .session import Base, create_postgres_tables, db_config  # , get_db

# Export all components that were previously available from postgres_db.py
__all__ = [
    # Session management
    "Base",
    # "engine",
    "db_config",
    "create_postgres_tables",
    # "get_db",
    # Models
    "Case",
    "Comment",
    "JiraCard",
    "JiraComment",
    # Operations
    "load_cases_postgres",
    "load_jira_cards_postgres",
]
