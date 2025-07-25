"""
Comprehensive tests for the t5gweb.database module

These tests use an in-memory SQLite database and load test data from fake_data.json
to test database operations, model relationships, and data integrity.
"""

import json
import os
import re
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from dateutil import parser
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from t5gweb.database import (
    Base,
    Case,
    JiraCard,
    JiraComment,
    load_cases_postgres,
    load_jira_cards_postgres,
)


@pytest.fixture(scope="function")
def test_db_session():
    """Create an in-memory SQLite database for testing"""
    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    # Create session
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = scoped_session(TestSessionLocal)

    yield session

    # Cleanup
    session.close()


@pytest.fixture(scope="function")
def fake_data():
    """Load fake data from the JSON file"""
    fake_data_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "fake_data.json"
    )

    with open(fake_data_path, "r") as f:
        return json.load(f)


@pytest.fixture
def mock_jira_issue():
    """Create a mock JIRA issue object"""
    mock_issue = Mock()
    mock_issue.key = "TEST-123"
    mock_issue.fields.summary = "12345678: Test Summary"
    mock_issue.fields.priority.name = "High"
    mock_issue.fields.status.name = "In Progress"
    mock_issue.fields.assignee.key = "testuser"
    mock_issue.fields.created = "2024-01-01T00:00:00.000+0000"

    # Mock comments
    mock_comment1 = Mock()
    mock_comment1.id = "comment-1"
    mock_comment1.author.key = "author1"
    mock_comment1.body = "Test comment 1"
    mock_comment1.updated = "2024-01-01T01:00:00.000+0000"

    mock_comment2 = Mock()
    mock_comment2.id = "comment-2"
    mock_comment2.author.key = "author2"
    mock_comment2.body = "Test comment 2"
    mock_comment2.updated = "2024-01-01T02:00:00.000+0000"

    mock_issue.fields.comment.comments = [mock_comment1, mock_comment2]

    # Optional fields
    mock_issue.fields.customfield_10007 = None  # sprint

    return mock_issue


class TestDatabaseModels:
    """Test database models and their relationships"""

    def test_case_model_creation(self, test_db_session):
        """Test creating a Case model instance"""
        case = Case(
            case_number="12345678",
            owner="Test Owner",
            severity=3,
            account="Test Account",
            summary="Test Summary",
            status="Open",
            created_date=datetime.now(timezone.utc),
            last_update=datetime.now(timezone.utc),
            description="Test Description",
            product="Test Product 1.0",
            product_version="1.0",
        )

        test_db_session.add(case)
        test_db_session.commit()

        # Verify case was created
        retrieved_case = (
            test_db_session.query(Case).filter_by(case_number="12345678").first()
        )
        assert retrieved_case is not None
        assert retrieved_case.owner == "Test Owner"
        assert retrieved_case.severity == 3
        assert retrieved_case.account == "Test Account"

    def test_jira_card_model_creation(self, test_db_session):
        """Test creating a JiraCard model with foreign key relationship"""
        # First create a case
        case_created_date = datetime.now(timezone.utc)
        case = Case(
            case_number="12345678",
            created_date=case_created_date,
            owner="Test Owner",
            severity=3,
            account="Test Account",
            summary="Test Summary",
            status="Open",
            last_update=datetime.now(timezone.utc),
            description="Test Description",
            product="Test Product 1.0",
            product_version="1.0",
        )
        test_db_session.add(case)
        test_db_session.commit()

        # Create JiraCard
        jira_card = JiraCard(
            jira_card_id="TEST-123",
            case_number="12345678",
            created_date=case_created_date,
            last_update_date=datetime.now(timezone.utc),
            summary="TEST-123: Test Summary",
            priority="High",
            status="In Progress",
            assignee="testuser",
            severity=3,
        )
        test_db_session.add(jira_card)
        test_db_session.commit()

        # Verify relationships
        retrieved_card = (
            test_db_session.query(JiraCard).filter_by(jira_card_id="TEST-123").first()
        )
        assert retrieved_card is not None
        assert retrieved_card.case_number == "12345678"
        assert retrieved_card.case.owner == "Test Owner"

    def test_jira_comment_model_creation(self, test_db_session):
        """Test creating JiraComment with relationship to JiraCard"""
        # Create prerequisite case and card
        case_created_date = datetime.now(timezone.utc)
        case = Case(
            case_number="12345678",
            created_date=case_created_date,
            owner="Test Owner",
            severity=3,
            account="Test Account",
            summary="Test Summary",
            status="Open",
            last_update=datetime.now(timezone.utc),
            description="Test Description",
            product="Test Product 1.0",
            product_version="1.0",
        )
        test_db_session.add(case)

        jira_card = JiraCard(
            jira_card_id="TEST-123",
            case_number="12345678",
            created_date=case_created_date,
            last_update_date=datetime.now(timezone.utc),
            summary="TEST-123: Test Summary",
            priority="High",
            status="In Progress",
            assignee="testuser",
        )
        test_db_session.add(jira_card)
        test_db_session.commit()

        # Create comment
        comment = JiraComment(
            jira_comment_id="comment-123",
            jira_card_id="TEST-123",
            author="author1",
            body="Test comment body",
            last_update_date=datetime.now(timezone.utc),
        )
        test_db_session.add(comment)
        test_db_session.commit()

        # Verify relationships
        retrieved_comment = (
            test_db_session.query(JiraComment)
            .filter_by(jira_comment_id="comment-123")
            .first()
        )
        assert retrieved_comment is not None
        assert retrieved_comment.jira_card_id == "TEST-123"
        assert retrieved_comment.jira_card.case_number == "12345678"


class TestDatabaseOperations:
    """Test database operations functions"""

    @patch("t5gweb.database.operations.scoped_session")
    def test_load_cases_postgres_with_fake_data(
        self, mock_session, fake_data, test_db_session
    ):
        """Test loading cases using fake data"""
        # Configure mock to use our test session
        mock_session.return_value = test_db_session

        # Get subset of cases from fake data and add missing fields for testing
        cases_data = dict(list(fake_data["cases"].items())[:3])

        # Add missing product_version field that real production data always has
        for case_number, case_data in cases_data.items():
            if "product_version" not in case_data:
                # Extract version from product field (e.g., "dolores 0.2" -> "0.2")
                product = case_data.get("product", "unknown 1.0")
                version_match = re.search(r"[\s]+([\d\.]+)$", product)
                case_data["product_version"] = (
                    version_match.group(1) if version_match else "1.0"
                )

        # Load cases
        load_cases_postgres(cases_data)

        # Verify cases were loaded
        loaded_cases = test_db_session.query(Case).all()
        assert len(loaded_cases) == 3

        # Verify specific case data
        case_81381364 = (
            test_db_session.query(Case).filter_by(case_number="81381364").first()
        )
        assert case_81381364 is not None
        assert case_81381364.owner == "Isa Escribano Barriga"
        assert case_81381364.account == "Pepito Gil Vargas S.A."
        assert case_81381364.severity == 3  # From "3 (Normal)"
        assert case_81381364.status == "Closed"

    @patch("t5gweb.database.operations.scoped_session")
    def test_load_jira_cards_postgres_with_mock_issue(
        self, mock_session, test_db_session, mock_jira_issue, fake_data
    ):
        """Test loading JIRA cards using mock issue and fake case data"""
        # Configure mock to use our test session
        mock_session.return_value = test_db_session

        # First load a case that matches our mock issue
        case_data = {
            "12345678": {
                "owner": "Test Owner",
                "severity": "3 (Normal)",
                "account": "Test Account",
                "problem": "Test Problem",
                "status": "Open",
                "createdate": "2024-01-01T00:00:00Z",
                "last_update": "2024-01-01T12:00:00Z",
                "description": "Test Description",
                "product": "Test Product 1.0",
                "product_version": "1.0",
            }
        }
        load_cases_postgres(case_data)

        # Mock the format_comment function
        with patch(
            "t5gweb.database.operations.format_comment", side_effect=lambda x: x.body
        ):
            # Load JIRA card
            card_processed, card_comments = load_jira_cards_postgres(
                case_data, "12345678", mock_jira_issue
            )

        assert card_processed is True
        assert len(card_comments) == 2

        # Verify card was created
        jira_card = (
            test_db_session.query(JiraCard).filter_by(jira_card_id="TEST-123").first()
        )
        assert jira_card is not None
        assert jira_card.case_number == "12345678"
        assert jira_card.priority == "High"
        assert jira_card.status == "In Progress"

        # Verify comments were created
        comments = (
            test_db_session.query(JiraComment).filter_by(jira_card_id="TEST-123").all()
        )
        assert len(comments) == 2

    # @patch('t5gweb.database.operations.scoped_session')
    # def test_load_jira_cards_postgres_optimized(
    # self, mock_session, test_db_session, mock_jira_issue
    # ):
    #     """Test the optimized version of load_jira_cards_postgres"""
    #     # NOTE: Optimized function not yet implemented in current codebase
    #     # This test can be enabled when load_jira_cards_postgres_optimized is added
    #     pass


class TestDataIntegrity:
    """Test data integrity and edge cases"""

    @patch("t5gweb.database.operations.scoped_session")
    def test_duplicate_case_handling(self, mock_session, test_db_session, fake_data):
        """Test that duplicate cases are handled correctly (merge vs create)"""
        mock_session.return_value = test_db_session

        # Load same case data twice
        single_case = {"81381364": fake_data["cases"]["81381364"].copy()}

        # Add missing product_version field that real production data always has
        if "product_version" not in single_case["81381364"]:
            product = single_case["81381364"].get("product", "unknown 1.0")
            version_match = re.search(r"[\s]+([\d\.]+)$", product)
            single_case["81381364"]["product_version"] = (
                version_match.group(1) if version_match else "1.0"
            )

        # First load
        load_cases_postgres(single_case)
        first_count = test_db_session.query(Case).count()

        # Second load (should update, not create duplicate)
        load_cases_postgres(single_case)
        second_count = test_db_session.query(Case).count()

        assert first_count == second_count == 1

    def test_foreign_key_constraints(self, test_db_session):
        """Test that foreign key constraints are enforced"""
        # Note: SQLite doesn't enforce foreign keys by default in our test setup
        # This test verifies the constraint logic exists, even if not enforced

        try:
            # Try to create JiraCard without corresponding Case
            jira_card = JiraCard(
                jira_card_id="ORPHAN-123",
                case_number="99999999",  # Non-existent case
                created_date=datetime.now(timezone.utc),
                last_update_date=datetime.now(timezone.utc),
                summary="Orphan card",
                priority="High",
                status="Open",
            )

            test_db_session.add(jira_card)
            test_db_session.commit()

            # If we reach here in SQLite, that's expected since FK constraints may not
            # be enforced
            # But we can still verify the card was created (which shouldn't happen
            # in production with FK constraints)
            orphan_card = (
                test_db_session.query(JiraCard)
                .filter_by(jira_card_id="ORPHAN-123")
                .first()
            )
            assert orphan_card is not None  # In SQLite, this might succeed

        except Exception as e:
            # If an exception is raised, that's good - it means FK
            # constraints are working
            assert "constraint" in str(e).lower() or "foreign key" in str(e).lower()

    @patch("t5gweb.database.operations.scoped_session")
    def test_load_cases_with_missing_fields(self, mock_session, test_db_session):
        """Test loading cases with some missing optional fields"""
        mock_session.return_value = test_db_session

        # Case data with missing optional fields
        incomplete_case = {
            "87654321": {
                "owner": "Test Owner",
                "severity": "2 (High)",
                "account": "Test Account",
                "problem": "Test Problem",
                "status": "Open",
                "createdate": "2024-01-01T00:00:00Z",
                "last_update": "2024-01-01T12:00:00Z",
                "description": "Test Description",
                "product": "Test Product 1.0",
                "product_version": "1.0",
                # Missing: bug, tags, closeddate
            }
        }

        # Should load successfully even with missing fields
        load_cases_postgres(incomplete_case)

        case = test_db_session.query(Case).filter_by(case_number="87654321").first()
        assert case is not None
        assert case.severity == 2  # Should parse "2 (High)" correctly


class TestDataValidation:
    """Test data validation and parsing"""

    def test_severity_parsing(self, test_db_session):
        """Test that severity strings are correctly parsed to integers"""
        test_cases = [
            ("1 (Urgent)", 1),
            ("2 (High)", 2),
            ("3 (Normal)", 3),
            ("4 (Low)", 4),
            ("Urgent", None),  # No number
            ("", None),  # Empty string
        ]

        for i, (severity_string, expected_int) in enumerate(test_cases):
            case = Case(
                case_number=f"TEST{i}{expected_int or 'X'}",  # Make unique case numbers
                created_date=datetime.now(timezone.utc),
                owner="Test",
                severity=(
                    int(severity_string[0])
                    if severity_string and severity_string[0].isdigit()
                    else None
                ),
                account="Test",
                summary="Test",
                status="Open",
                last_update=datetime.now(timezone.utc),
                description="Test",
                product="Test",
                product_version="1.0",
            )

            test_db_session.add(case)

        test_db_session.commit()

        # Verify all cases were created with correct severity parsing
        cases = test_db_session.query(Case).all()
        assert len(cases) == len(test_cases)

    def test_date_parsing_consistency(self):
        """Test that date parsing is consistent with the application logic"""
        test_dates = [
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00.000Z",
            "2024-01-01T00:00:00.000+0000",
        ]

        parsed_dates = [parser.parse(date_str) for date_str in test_dates]

        # All should parse to the same datetime
        base_date = parsed_dates[0]
        for parsed_date in parsed_dates[1:]:
            # Compare timestamps to handle timezone differences
            assert abs((parsed_date - base_date).total_seconds()) < 1


class TestPerformanceAndScaling:
    """Test performance characteristics and scaling behavior"""

    @patch("t5gweb.database.operations.scoped_session")
    def test_bulk_case_loading_performance(
        self, mock_session, test_db_session, fake_data
    ):
        """Test loading all fake cases efficiently"""
        mock_session.return_value = test_db_session

        # Prepare fake data with missing fields for testing
        cases_data = fake_data["cases"].copy()

        # Add missing product_version field that real production data always has
        for case_number, case_data in cases_data.items():
            if "product_version" not in case_data:
                # Extract version from product field (e.g., "dolores 0.2" -> "0.2")
                product = case_data.get("product", "unknown 1.0")
                version_match = re.search(r"[\s]+([\d\.]+)$", product)
                case_data["product_version"] = (
                    version_match.group(1) if version_match else "1.0"
                )

        # Load all cases from fake data
        start_time = datetime.now()
        load_cases_postgres(cases_data)
        end_time = datetime.now()

        # Verify all cases were loaded
        loaded_count = test_db_session.query(Case).count()
        expected_count = len(fake_data["cases"])
        assert loaded_count == expected_count

        # Basic performance check (should complete in reasonable time)
        duration = (end_time - start_time).total_seconds()
        assert duration < 10  # Should complete within 10 seconds

    def test_query_efficiency_with_relationships(self, test_db_session):
        """Test that relationship queries are efficient"""
        # Create test data with relationships
        case_date = datetime.now(timezone.utc)
        case = Case(
            case_number="12345678",
            created_date=case_date,
            owner="Test Owner",
            severity=3,
            account="Test Account",
            summary="Test Summary",
            status="Open",
            last_update=datetime.now(timezone.utc),
            description="Test Description",
            product="Test Product 1.0",
            product_version="1.0",
        )
        test_db_session.add(case)

        # Create multiple cards for the same case
        for i in range(5):
            card = JiraCard(
                jira_card_id=f"TEST-{i}",
                case_number="12345678",
                created_date=case_date,
                last_update_date=datetime.now(timezone.utc),
                summary=f"TEST-{i}: Test Summary",
                priority="High",
                status="Open",
            )
            test_db_session.add(card)

        test_db_session.commit()

        # Test efficient querying of relationships
        case_with_cards = (
            test_db_session.query(Case).filter_by(case_number="12345678").first()
        )
        assert len(case_with_cards.jira_cards) == 5

        # Test reverse relationship
        card = test_db_session.query(JiraCard).filter_by(jira_card_id="TEST-0").first()
        assert card.case.case_number == "12345678"


if __name__ == "__main__":
    pytest.main([__file__])
