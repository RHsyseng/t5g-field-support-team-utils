"""Database session and connection management"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from t5gweb.utils import set_cfg

cfg = set_cfg()

# Database setup
DATABASE_URL = (
    f"postgresql://{cfg['postgresql_username']}:"
    f"{cfg['postgresql_password']}@{cfg['postgresql_ip']}"
    f":{cfg['postgresql_port']}/{cfg['postgresql_dbname']}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# Create tables - this will be called after models are imported
def create_postgres_tables():
    Base.metadata.create_all(bind=engine)


# Dependency injection
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
