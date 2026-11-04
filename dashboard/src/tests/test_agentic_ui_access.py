"""
Tests for the agentic UI access control.

Covers get_agentic_ui_allowed_users() and agentic_ui_access_allowed() from
t5gweb.utils - the allow-list that gates the /agent page and every
/api/ai/* endpoint. Users are identified by their SAML mail attribute, the
same identity My Queue filters on.
"""

import os
from unittest.mock import patch

from t5gweb.utils import (
    agentic_ui_access_allowed,
    get_agentic_ui_allowed_users,
    set_cfg,
)


def _access_env(allowed="", login_disabled="false", user_override=""):
    """Build the env overlay the access check reads.

    Args:
        allowed: Value for agentic_ui_allowed_users. "" stands for unset
            (both deny everyone); pass None to leave the variable untouched.
        login_disabled: Value for FLASK_LOGIN_DISABLED.
        user_override: Value for the AGENTIC_USER_EMAIL dev override
            ("" stands for unset).

    Returns:
        dict: Env var overrides for patch.dict.
    """
    env = {
        "FLASK_LOGIN_DISABLED": login_disabled,
        "AGENTIC_USER_EMAIL": user_override,
    }
    if allowed is not None:
        env["agentic_ui_allowed_users"] = allowed
    return env


class TestGetAgenticUiAllowedUsers:
    """Parsing of the agentic_ui_allowed_users JSON array."""

    def test_unset_yields_empty_set(self):
        with patch.dict(os.environ, _access_env(""), clear=False):
            assert get_agentic_ui_allowed_users() == set()

    def test_empty_array_yields_empty_set(self):
        with patch.dict(os.environ, _access_env("[]"), clear=False):
            assert get_agentic_ui_allowed_users() == set()

    def test_json_array_is_parsed_and_normalized(self):
        with patch.dict(
            os.environ,
            _access_env('["Someone@RedHat.com", " other@redhat.com "]'),
            clear=False,
        ):
            assert get_agentic_ui_allowed_users() == {
                "someone@redhat.com",
                "other@redhat.com",
            }

    def test_quoted_json_string_is_tolerated(self):
        with patch.dict(os.environ, _access_env('"someone@redhat.com"'), clear=False):
            assert get_agentic_ui_allowed_users() == {"someone@redhat.com"}

    def test_invalid_json_denies_everyone(self):
        # A bare unquoted address is not valid JSON: fail closed.
        with patch.dict(os.environ, _access_env("someone@redhat.com"), clear=False):
            assert get_agentic_ui_allowed_users() == set()

    def test_truncated_json_denies_everyone(self):
        with patch.dict(os.environ, _access_env('["someone@redhat.com"'), clear=False):
            assert get_agentic_ui_allowed_users() == set()

    def test_non_list_json_denies_everyone(self):
        with patch.dict(
            os.environ, _access_env('{"email": "a@redhat.com"}'), clear=False
        ):
            assert get_agentic_ui_allowed_users() == set()

    def test_non_string_entries_are_ignored(self):
        with patch.dict(
            os.environ, _access_env('[1, null, "someone@redhat.com"]'), clear=False
        ):
            assert get_agentic_ui_allowed_users() == {"someone@redhat.com"}


class TestAgenticUiAccessAllowed:
    """The access decision for /agent and the /api/ai/* endpoints."""

    def test_unconfigured_denies_everyone(self):
        with patch.dict(os.environ, _access_env(""), clear=False):
            assert agentic_ui_access_allowed("someone@redhat.com") is False

    def test_empty_list_denies_everyone(self):
        with patch.dict(os.environ, _access_env("[]"), clear=False):
            assert agentic_ui_access_allowed("someone@redhat.com") is False

    def test_allowed_user_is_allowed(self):
        with patch.dict(os.environ, _access_env('["someone@redhat.com"]'), clear=False):
            assert agentic_ui_access_allowed("someone@redhat.com") is True

    def test_match_is_case_and_whitespace_insensitive(self):
        with patch.dict(os.environ, _access_env('["Someone@RedHat.com"]'), clear=False):
            assert agentic_ui_access_allowed(" someone@redhat.com ") is True

    def test_other_user_is_denied(self):
        with patch.dict(os.environ, _access_env('["someone@redhat.com"]'), clear=False):
            assert agentic_ui_access_allowed("other@redhat.com") is False

    def test_missing_identity_is_denied(self):
        with patch.dict(os.environ, _access_env('["someone@redhat.com"]'), clear=False):
            assert agentic_ui_access_allowed(None) is False
            assert agentic_ui_access_allowed("") is False

    def test_anonymous_with_auth_enabled_is_denied(self):
        # Authentication enabled but no session (e.g. the login page
        # rendering the nav): there is no identity to authorize.
        with patch.dict(os.environ, _access_env('["someone@redhat.com"]'), clear=False):
            assert agentic_ui_access_allowed(None) is False

    def test_dev_mode_without_override_stays_open(self):
        # FLASK_LOGIN_DISABLED=true (local dev) with no simulated user and
        # no allow-list configured: the tool stays open for development.
        with patch.dict(
            os.environ, _access_env("", login_disabled="true"), clear=False
        ):
            assert agentic_ui_access_allowed(None) is True

    def test_dev_override_on_the_list_is_allowed(self):
        with patch.dict(
            os.environ,
            _access_env(
                '["someone@redhat.com"]',
                login_disabled="true",
                user_override="Someone@RedHat.com",
            ),
            clear=False,
        ):
            assert agentic_ui_access_allowed(None) is True

    def test_dev_override_off_the_list_is_denied(self):
        with patch.dict(
            os.environ,
            _access_env(
                '["someone@redhat.com"]',
                login_disabled="true",
                user_override="other@redhat.com",
            ),
            clear=False,
        ):
            assert agentic_ui_access_allowed(None) is False

    def test_dev_override_with_empty_list_is_denied(self):
        with patch.dict(
            os.environ,
            _access_env(
                "[]", login_disabled="true", user_override="someone@redhat.com"
            ),
            clear=False,
        ):
            assert agentic_ui_access_allowed(None) is False

    def test_real_identity_outranks_the_dev_override(self):
        # A real session decides access even when AGENTIC_USER_EMAIL leaks
        # into an environment: the override never outranks a real identity.
        with patch.dict(
            os.environ,
            _access_env('["someone@redhat.com"]', user_override="other@redhat.com"),
            clear=False,
        ):
            assert agentic_ui_access_allowed("someone@redhat.com") is True

    def test_set_cfg_exposes_the_allow_list(self):
        with patch.dict(os.environ, _access_env('["someone@redhat.com"]'), clear=False):
            cfg = set_cfg()
        assert cfg["agentic_ui_allowed_users"] == {"someone@redhat.com"}
