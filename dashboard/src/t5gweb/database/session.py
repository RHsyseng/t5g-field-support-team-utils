"""Database session and connection management"""

import threading
from typing import Optional

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from t5gweb.utils import set_cfg

cfg = set_cfg()


def get_database_url():
    """Build database URL from configuration"""
    url_object = URL.create(
        "postgresql",
        username=cfg["postgresql_username"],
        password=cfg["postgresql_password"],
        host=cfg["postgresql_ip"],
        port=cfg["postgresql_port"],
        database=cfg["postgresql_dbname"],
    )
    return url_object


class DatabaseConfig:
    def __init__(self):
        self._engine: Optional[create_engine] = None
        self._session_local: Optional[sessionmaker] = None
        self._lock = threading.Lock()

    @property
    def engine(self) -> create_engine:
        """Lazy initialize the database engine"""
        if not self._engine:
            with self._lock:
                if not self._engine:
                    DATABASE_URL = get_database_url()
                    self._engine = create_engine(
                        DATABASE_URL,
                        pool_pre_ping=True,
                        pool_recycle=3600,
                        connect_args={"connect_timeout": 10},
                    )
        return self._engine

    @property
    def SessionLocal(self) -> sessionmaker:
        """Lazy initialize the session maker"""
        if not self._session_local:
            with self._lock:
                if not self._session_local:
                    self._session_local = sessionmaker(
                        autocommit=False, autoflush=False, bind=self.engine
                    )
        return self._session_local


db_config = DatabaseConfig()


# check_postgres_config(cfg)

# DATABASE_URL = get_database_url()

# engine = create_engine(DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# Create tables - this will be called after models are imported
def create_postgres_tables():
    Base.metadata.create_all(bind=db_config.engine)


# Dependency injection
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()
