"""
Shared pytest configuration and fixtures for t5gweb tests
"""

import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from t5gweb.database import Base


@pytest.fixture(scope="session")
def fake_data():
    """Load fake data from JSON file once per test session"""
    fake_data_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "fake_data.json"
    )

    with open(fake_data_path, "r") as f:
        return json.load(f)


@pytest.fixture(scope="function")
def test_db_engine():
    """Create a test database engine using SQLite in-memory database"""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,  # Set to True for SQL debugging
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="function")
def test_db_session(test_db_engine):
    """Create a test database session"""
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_db_engine
    )
    session = scoped_session(TestSessionLocal)

    yield session

    # Cleanup
    session.close()


@pytest.fixture(autouse=True)
def mock_database_config(test_db_engine):
    """Patch DatabaseConfig to use test database"""
    from t5gweb.database.session import db_config

    # Create a test session maker
    TestSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_db_engine
    )

    # Create a mock that returns a session instance when called
    def mock_session_local():
        return TestSessionLocal()

    # Patch the underlying attributes and the SessionLocal method
    with patch.object(db_config, "_engine", test_db_engine), patch.object(
        db_config, "_session_local", TestSessionLocal
    ), patch.object(
        db_config, "SessionLocal", mock_session_local
    ):
        yield


@pytest.fixture
def sample_case_data():
    """Provide sample case data for testing"""
    return {
        "12345678": {
            "owner": "Test Owner",
            "severity": "3 (Normal)",
            "account": "Test Account",
            "problem": "Test Problem Summary",
            "status": "Open",
            "createdate": "2024-01-01T00:00:00Z",
            "last_update": "2024-01-01T12:00:00Z",
            "description": "Test case description",
            "product": "Test Product 1.0",
            "product_version": "1.0",
        }
    }


@pytest.fixture
def sample_case_with_bug():
    """Provide sample case data with bug information"""
    return {
        "87654321": {
            "owner": "Bug Owner",
            "severity": "2 (High)",
            "account": "Bug Account",
            "problem": "Bug Problem Summary",
            "status": "Waiting on Red Hat",
            "createdate": "2024-01-15T00:00:00Z",
            "last_update": "2024-01-15T12:00:00Z",
            "description": "Bug case description",
            "product": "Bug Product 2.0",
            "product_version": "2.0",
            "bug": "1234567",
        }
    }


# Test markers for different test categories
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "performance: mark test as a performance test")
    config.addinivalue_line("markers", "database: mark test as requiring database")
