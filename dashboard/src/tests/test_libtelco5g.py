import pytest
from t5gweb.libtelco5g import (get_case_number, is_bug_missing_target,
                               jira_connection, redis_get, redis_set)


def test_get_jira_connection(mocker):
    cfg = {"server": "http://example.com", "password": "your_token"}
    mock_jira = mocker.patch("t5gweb.libtelco5g.JIRA")

    result = jira_connection(cfg)

    mock_jira.assert_called_once_with(server=cfg["server"], token_auth=cfg["password"])
    assert result == mock_jira.return_value


@pytest.fixture
def mock_redis(mocker):
    return mocker.patch("t5gweb.libtelco5g.redis.Redis")


def test_redis_set(mock_redis):
    key = "test_key"
    value = "test_value"
    redis_set(key, value)

    mock_redis.assert_called_once_with(host="redis")
    mock_redis.return_value.mset.assert_called_once_with({key: value})


@pytest.mark.parametrize(
    "key,value,expected_result",
    [("test_key", b'{"foo": "bar"}', {"foo": "bar"}), ("test_none", None, {})],
)
def test_redis_get(key, value, expected_result, mock_redis):
    mock_redis.return_value.get.return_value = value

    result = redis_get(key)

    mock_redis.assert_called_once_with(host="redis")
    mock_redis.return_value.get.assert_called_once_with(key)
    assert result == expected_result


@pytest.mark.parametrize(
    "link, pfilter, expected_case_number",
    [
        ("https://access.redhat.com/support/cases/0123456", "cases", "0123456"),
        ("https://access.redhat.com/support/cases/#/case/0123456", "cases", "0123456"),
        ("https://example.com/support/cases/0123456", "cases", ""),
        ("https://access.redhat.com/support/cases/0123456", "invalid_filter", ""),
        ("", "cases", ""),
    ],
)
def test_get_case_number(link, pfilter, expected_case_number):
    result = get_case_number(link, pfilter)
    assert result == expected_case_number


@pytest.mark.parametrize(
    "item,expected_result",
    [
        ({"target_release": ["---"]}, True),
        ({"target_release": ["4.14"]}, False),
        ({"fix_versions": ["4.14"]}, False),
        ({"fix_versions": ["---"]}, True),
        ({"fix_versions": None}, True),
        ({"nothing": ["4.14"]}, True),
    ],
)
def test_is_bug_missing_target(item, expected_result):
    result = is_bug_missing_target(item)
    assert result == expected_result
