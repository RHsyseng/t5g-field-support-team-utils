# models.py - Define database models
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
