"""Database session and connection management"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:secret@postgresql/dashboard")

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