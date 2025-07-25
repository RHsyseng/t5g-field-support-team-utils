# T5GWeb Database Module Tests

This directory contains comprehensive tests for the `t5gweb.database` module, including models, operations, and data integrity testing.

## Test Structure

### Test Files

- **`test_database.py`** - Comprehensive database module tests
- **`test_libtelco5g.py`** - Existing libtelco5g utility tests
- **`test_utils.py`** - Existing utility function tests
- **`conftest.py`** - Shared pytest fixtures and configuration
- **`pytest.ini`** - Pytest configuration settings

### Test Categories

The tests are organized into several categories:

1. **TestDatabaseModels** - Test SQLAlchemy model creation and relationships
2. **TestDatabaseOperations** - Test database operation functions
3. **TestDataIntegrity** - Test data consistency and constraint enforcement
4. **TestDataValidation** - Test data parsing and validation logic
5. **TestPerformanceAndScaling** - Test performance characteristics

## Test Data

Tests use realistic data from `src/data/fake_data.json` which contains:

- **cases** - Support case data with various statuses and severities
- **cards** - Jira card data with relationships to cases
- **issues** - Jira issue data linked to cases
- **bugs** - Bugzilla data associated with cases

## Database Testing Approach

### SQLite In-Memory Database

Tests use an in-memory SQLite database for:
- **Fast execution** - No disk I/O overhead
- **Isolation** - Each test gets a fresh database
- **Portability** - No external database dependencies
- **CI/CD friendly** - Runs anywhere without setup

### Mock Objects

Tests use mocked Jira objects to simulate API responses without external dependencies.

## Setup and Installation

### Install Test Dependencies

```bash
cd dashboard/src
pip install -r tests/requirements-test.txt
```

### Install Project Dependencies

```bash
pip install -e .
```

## Running Tests

### Run All Tests

```bash
# From the dashboard/src directory
pytest

# With coverage reporting
pytest --cov=t5gweb/database --cov-report=html
```

### Run Specific Test Categories

```bash
# Database-specific tests only
pytest -m database

# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Performance tests only
pytest -m performance
```

### Run Specific Test Files

```bash
# Database module tests only
pytest tests/test_database.py

# Specific test class
pytest tests/test_database.py::TestDatabaseModels

# Specific test method
pytest tests/test_database.py::TestDatabaseModels::test_case_model_creation
```

### Verbose Output

```bash
# Extra verbose output
pytest -vv

# Show output from print statements
pytest -s

# Both verbose and output
pytest -vv -s
```

## Test Coverage

The tests cover:

### Model Testing
- ✅ Case model creation and validation
- ✅ JiraCard model with foreign key relationships
- ✅ JiraComment model with cascading relationships
- ✅ Database constraint enforcement

### Operation Testing
- ✅ `load_cases_postgres()` with real fake data
- ✅ `load_jira_cards_postgres()` with mock Jira issues
- ✅ `load_jira_cards_postgres_optimized()` performance version
- ✅ Duplicate handling and data merging

### Data Integrity Testing
- ✅ Foreign key constraint enforcement
- ✅ Duplicate case handling (merge vs create)
- ✅ Missing field handling
- ✅ Data validation and parsing

### Performance Testing
- ✅ Bulk data loading performance
- ✅ Relationship query efficiency
- ✅ Large dataset handling

## Expected Test Results

When running the full test suite, you should see:

```
========================= test session starts =========================
collected 18 items

tests/test_database.py::TestDatabaseModels::test_case_model_creation PASSED
tests/test_database.py::TestDatabaseModels::test_jira_card_model_creation PASSED
tests/test_database.py::TestDatabaseModels::test_jira_comment_model_creation PASSED
tests/test_database.py::TestDatabaseOperations::test_load_cases_postgres_with_fake_data PASSED
tests/test_database.py::TestDatabaseOperations::test_load_jira_cards_postgres_with_mock_issue PASSED
tests/test_database.py::TestDatabaseOperations::test_load_jira_cards_postgres_optimized PASSED
tests/test_database.py::TestDataIntegrity::test_duplicate_case_handling PASSED
tests/test_database.py::TestDataIntegrity::test_foreign_key_constraints PASSED
tests/test_database.py::TestDataIntegrity::test_load_cases_with_missing_fields PASSED
tests/test_database.py::TestDataValidation::test_severity_parsing PASSED
tests/test_database.py::TestDataValidation::test_date_parsing_consistency PASSED
tests/test_database.py::TestPerformanceAndScaling::test_bulk_case_loading_performance PASSED
tests/test_database.py::TestPerformanceAndScaling::test_query_efficiency_with_relationships PASSED

========================= 13 passed in 2.34s =========================
```

## Continuous Integration

These tests are designed to be CI/CD friendly:

- No external database dependencies
- Fast execution (typically under 5 seconds)
- Deterministic results
- Clear pass/fail indicators

## Extending Tests

To add new tests:

1. **Model tests** - Add to `TestDatabaseModels` class
2. **Operation tests** - Add to `TestDatabaseOperations` class
3. **New test files** - Follow `test_*.py` naming convention
4. **Fixtures** - Add reusable fixtures to `conftest.py`

## Troubleshooting

### Common Issues

1. **Import errors** - Ensure you're running from `dashboard/src` directory
2. **Missing dependencies** - Install test requirements: `pip install -r tests/requirements-test.txt`
3. **Slow tests** - Check if using correct in-memory SQLite (not file-based)
4. **Failed assertions** - Use `-vv` flag for detailed assertion output

### Debug Mode

Enable SQL debugging by setting `echo=True` in the `test_db_engine` fixture in `conftest.py`.

## Contributing

When adding new database functionality:

1. Write tests first (TDD approach)
2. Test both success and failure cases
3. Include performance considerations for bulk operations
4. Use realistic test data from `fake_data.json`
5. Mock external dependencies (Jira, Redis, etc.)
