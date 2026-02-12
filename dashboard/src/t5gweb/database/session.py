"""Database session and connection management"""

import threading
from typing import Optional

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from t5gweb.utils import set_cfg


class DatabaseConfig:
    """Database configuration and session management with execution context awareness

    Manages PostgreSQL database connections with different session strategies
    for web requests vs Celery workers. Web requests use cached sessionmaker
    while Celery workers get fresh sessions to avoid connection issues across
    process boundaries.

    Thread-safe lazy initialization of database engine with connection pooling
    and automatic ping testing.
    """

    def __init__(self):
        self._engine: Optional[create_engine] = None  # type: ignore
        self._session_local: Optional[sessionmaker] = None
        self._lock = threading.Lock()

    @staticmethod
    def get_execution_context():
        """Detect execution context (web vs Celery worker)

        Determines if code is running in a Celery worker process or web
        application context by checking environment variables and process name.

        Returns:
            str: 'celery' if running in Celery worker, 'web' otherwise
        """
        import os

        # Check for Celery worker environment variables
        if any(key in os.environ for key in ["CELERY_WORKER_PROCESS", "C_FORCE_ROOT"]):
            return "celery"
        # Check if current process name contains celery
        import sys

        if "celery" in sys.argv[0].lower():
            return "celery"
        return "web"

    @staticmethod
    def get_database_url():
        """Build PostgreSQL database URL from configuration

        Constructs SQLAlchemy database URL using PostgreSQL connection
        parameters from application configuration.

        Returns:
            URL: SQLAlchemy URL object for PostgreSQL connection
        """
        cfg = set_cfg()
        url_object = URL.create(
            "postgresql+psycopg",
            username=cfg["POSTGRESQL_USER"],
            password=cfg["POSTGRESQL_PASSWORD"],
            host=cfg["POSTGRESQL_SERVICE_HOST"],
            port=cfg["POSTGRESQL_SERVICE_PORT"],
            database=cfg["POSTGRESQL_DATABASE"],
        )
        return url_object

    @property
    def engine(self) -> create_engine:  # type: ignore
        """Lazy initialize the database engine with connection pooling

        Creates database engine on first access with thread-safe initialization.
        Configured with connection pool pre-ping, 1-hour recycle time, and
        10-second connection timeout.

        Returns:
            Engine: SQLAlchemy database engine instance
        """
        if not self._engine:
            with self._lock:
                if not self._engine:
                    DATABASE_URL = self.get_database_url()
                    self._engine = create_engine(
                        DATABASE_URL,
                        pool_pre_ping=True,
                        pool_recycle=3600,
                        connect_args={"connect_timeout": 10},
                    )
        return self._engine

    def SessionLocal(self):
        """Create a new database session with context-aware strategy

        Returns different session types based on execution context:
        - Celery workers: Fresh session from new sessionmaker (non-scoped)
        - Web requests: Session from cached sessionmaker (scoped)

        This prevents connection issues in Celery workers where connections
        can't be shared across process boundaries.

        Returns:
            Session: SQLAlchemy database session instance
        """
        if self.get_execution_context() == "celery":
            # Return fresh session for Celery workers (non-scoped)
            sessionmaker_class = sessionmaker(
                autocommit=False, autoflush=False, bind=self.engine
            )
            return sessionmaker_class()
        else:
            # Return session from cached sessionmaker for web requests (scoped)
            if not self._session_local:
                with self._lock:
                    if not self._session_local:
                        self._session_local = sessionmaker(
                            autocommit=False, autoflush=False, bind=self.engine
                        )
            return self._session_local()


db_config = DatabaseConfig()


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all database models

    All database model classes should inherit from this base class to be
    properly registered with SQLAlchemy's ORM system.
    """

    pass


def create_postgres_tables():
    """Create all database tables defined in models

    Uses SQLAlchemy metadata to create all tables that don't already exist.
    Safe to call multiple times - only creates missing tables.

    Returns:
        None. Tables are created in PostgreSQL database.
    """
    Base.metadata.create_all(bind=db_config.engine)
