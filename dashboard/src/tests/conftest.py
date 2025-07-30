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

# Set up test environment variables immediately, before any other imports
# This ensures they're available during test collection when modules are imported
_original_env_values = {}
_test_env_vars = {
    "postgresql_username": "test_user",
    "postgresql_password": "test_pass",
    "postgresql_ip": "localhost",
    "postgresql_port": "5432",
    "postgresql_dbname": "test_db",
}

# Store original values and set test values
for key, value in _test_env_vars.items():
    _original_env_values[key] = os.environ.get(key)
    os.environ[key] = value


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Manage test environment variables lifecycle"""
    # Environment variables are already set at module level
    yield

    # Cleanup - restore original values
    for key, original_value in _original_env_values.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture(scope="function")
def mock_database_session(test_db_session):
    """Patch the database session functions to use test database"""
    from t5gweb.database import session

    # Patch the database session functions to use our test session
    with patch.object(session, "get_session_local") as mock_get_session_local:
        # Create a mock session class that returns our test session
        def mock_session_factory():
            return test_db_session

        mock_get_session_local.return_value = mock_session_factory

        # Also patch get_db to use our test session
        def mock_get_db():
            yield test_db_session

        with patch.object(session, "get_db", mock_get_db):
            yield test_db_session


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
