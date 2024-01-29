import pytest
import t5gweb.libtelco5g as libtelco5g


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
    result = libtelco5g.get_case_number(link, pfilter)
    assert result == expected_case_number


@pytest.mark.parametrize(
    "item,expected_result",
    [
        ({"target_release": ["---"]}, True),
        ({"target_release": ["4.14"]}, False),
        ({"fix_versions": ["4.14"]}, False),
        ({"fix_versions": ["---"]}, True),
        ({"fix_versions": None}, True),
        ({"nothing": ["4.14"]}, True)
    ],
)
def test_is_bug_missing_target(item, expected_result):
    result = libtelco5g.is_bug_missing_target(item)
    assert result == expected_result
