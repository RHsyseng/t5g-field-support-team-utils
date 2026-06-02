import pytest

from t5gweb.libtelco5g import (
    _assign_cases_batch,
    get_case_number,
    is_bug_missing_target,
    jira_connection,
    redis_get,
    redis_set,
)


def test_get_jira_connection(mocker):
    cfg = {
        "server": "http://example.com",
        "username": "test_user",
        "password": "your_token",
    }
    mock_jira = mocker.patch("t5gweb.libtelco5g.JIRA")

    result = jira_connection(cfg)

    mock_jira.assert_called_once_with(
        server=cfg["server"], basic_auth=(cfg["username"], cfg["password"])
    )
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


# --- _assign_cases_batch tests ---


@pytest.fixture
def team():
    return [
        {
            "name": "Alice",
            "jira_account_id": "a1",
            "jira_user": "alice",
            "accounts": ["Acme"],
            "active": "true",
        },
        {
            "name": "Bob",
            "jira_account_id": "b1",
            "jira_user": "bob",
            "accounts": ["Globex"],
            "active": "true",
        },
        {
            "name": "Carol",
            "jira_account_id": "c1",
            "jira_user": "carol",
            "accounts": [],
            "active": "true",
        },
    ]


@pytest.fixture
def cases():
    return {
        "001": {"account": "Acme Corp"},
        "002": {"account": "Acme Corp"},
        "003": {"account": "Globex Inc"},
        "004": {"account": "Unknown LLC"},
        "005": {"account": "Another Co"},
        "006": {"account": "Yet Another"},
    }


def test_multiple_cases_same_account_go_to_same_engineer(team, cases):
    # 001 and 002 are both Acme — both must land on Alice
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "002"], cases, cfg)

    assert result["001"]["jira_account_id"] == "a1"
    assert result["002"]["jira_account_id"] == "a1"


def test_account_assigned_engineers_excluded_when_cases_lte_team(team, cases):
    # 3 cases <= 3 engineers: 001->Alice, 003->Bob, 004 must go to Carol (not Alice/Bob)
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "003", "004"], cases, cfg)

    assert result["001"]["jira_account_id"] == "a1"
    assert result["003"]["jira_account_id"] == "b1"
    assert result["004"]["jira_account_id"] == "c1"


def test_multiple_account_cases_still_exclude_their_engineers(team, cases):
    # 4 cases, 3 engineers: 001+002->Alice, 003->Bob, 1 unmatched case (004)
    # 1 unmatched <= 3 team size, so account-assigned engineers are excluded —
    # 004 must go to Carol (the only non-account-assigned engineer)
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "002", "003", "004"], cases, cfg)

    assert result["001"]["jira_account_id"] == "a1"
    assert result["002"]["jira_account_id"] == "a1"
    assert result["003"]["jira_account_id"] == "b1"
    assert result["004"]["jira_account_id"] == "c1"


def test_account_assigned_engineers_excluded_even_with_multiple_account_cases(
    team, cases
):
    # 3 cases <= 3 engineers: 001+002 both go to Alice via account,
    # 004 is unmatched — pool must exclude Alice, so Carol gets it
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "002", "004"], cases, cfg)

    assert result["001"]["jira_account_id"] == "a1"
    assert result["002"]["jira_account_id"] == "a1"
    assert result["004"]["jira_account_id"] in {"b1", "c1"}


def test_overflow_reuses_all_engineers(team, cases):
    # 6 cases, 3 engineers — must cycle, all engineers used
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "002", "003", "004", "005", "006"], cases, cfg)

    assert len(result) == 6
    assigned_ids = {a["jira_account_id"] for a in result.values()}
    assert assigned_ids == {"a1", "b1", "c1"}


def test_no_team_returns_none_for_all_cases(cases):
    cfg = {"team": []}
    result = _assign_cases_batch(["004", "005"], cases, cfg)

    assert result == {"004": None, "005": None}


def test_displayname_always_set(team, cases):
    cfg = {"team": team}
    result = _assign_cases_batch(["001", "002", "004"], cases, cfg)

    for assignee in result.values():
        assert assignee["displayName"] == assignee["name"]
