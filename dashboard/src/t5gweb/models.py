# models.py - Define database models
from t5gweb.db import Base  # Import Base from db.py
from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from pydantic import BaseModel

class Case(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    case_number = Column(String, index=True)
    nested = Column(JSONB)

class CaseCreate(BaseModel):
    case_number: str
    nested: dict