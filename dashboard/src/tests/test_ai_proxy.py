"""Tests for the AI Agents proxy endpoints in t5gweb.api"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from flask import Flask
from flask_login import LoginManager

from t5gweb import api

UPSTREAM = "http://agents.test:8081"


@pytest.fixture
def client(monkeypatch):
    """Flask test client with only the API blueprint and login disabled

    No identity and FLASK_LOGIN_DISABLED=true leaves the agentic UI
    allow-list open (local dev mode), so the proxy itself can be tested.
    """
    monkeypatch.setenv("AI_AGENTS_API_URL", UPSTREAM + "/")
    monkeypatch.setenv("FLASK_LOGIN_DISABLED", "true")
    monkeypatch.delenv("ENGINEER_OVERRIDE", raising=False)
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.user_loader(lambda user_id: None)
    app.register_blueprint(api.BP)
    return app.test_client()


def make_response(status_code=200, body=None, json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    if json_error:
        resp.json.side_effect = requests.exceptions.JSONDecodeError("x", "<html>", 0)
    else:
        resp.json.return_value = body
    return resp


@pytest.fixture
def upstream():
    with patch("t5gweb.api.http_requests.request") as mock_request:
        mock_request.return_value = make_response(200, {"ok": True})
        yield mock_request


class TestProxyForwarding:
    def test_report_forwards_and_relays_json(self, client, upstream):
        upstream.return_value = make_response(200, {"id": "abc", "status": "done"})

        resp = client.get("/api/ai/report/case/01234567")

        assert resp.status_code == 200
        assert resp.get_json() == {"id": "abc", "status": "done"}
        upstream.assert_called_once_with(
            "get", f"{UPSTREAM}/report/case/01234567", timeout=api.AI_PROXY_TIMEOUT
        )

    def test_relays_upstream_status_code(self, client, upstream):
        upstream.return_value = make_response(404, {"error": "not found"})

        resp = client.get("/api/ai/report/case/01234567")

        assert resp.status_code == 404
        assert resp.get_json() == {"error": "not found"}

    @pytest.mark.parametrize(
        "query, expected",
        [("", "false"), ("?force=true", "true"), ("?force=TRUE", "true")],
    )
    def test_analyze_sends_lowercase_force_flag(
        self, client, upstream, query, expected
    ):
        client.post(f"/api/ai/analyze/01234567{query}")

        assert upstream.call_args.kwargs["params"] == {"force": expected}

    def test_feedback_post_forwards_json_object(self, client, upstream):
        resp = client.post("/api/ai/feedback/abc-123", json={"rating": "up"})

        assert resp.status_code == 200
        upstream.assert_called_once_with(
            "post",
            f"{UPSTREAM}/feedback/abc-123",
            timeout=api.AI_PROXY_TIMEOUT,
            json={"rating": "up"},
        )


class TestAccessControl:
    @pytest.mark.parametrize(
        "method, path",
        [
            ("get", "/api/ai/report/case/01234567"),
            ("post", "/api/ai/analyze/01234567"),
            ("get", "/api/ai/status/task-1"),
            ("post", "/api/ai/feedback/abc-123"),
        ],
    )
    def test_user_off_the_allow_list_gets_403(
        self, client, upstream, monkeypatch, method, path
    ):
        monkeypatch.setenv("agentic_ui_allowed_users", '["someone@redhat.com"]')
        monkeypatch.setenv("ENGINEER_OVERRIDE", "other@redhat.com")

        resp = getattr(client, method)(path, json={})

        assert resp.status_code == 403
        assert resp.get_json() == {"error": "Not authorized to use AI agent features"}
        upstream.assert_not_called()

    def test_user_on_the_allow_list_is_proxied(self, client, upstream, monkeypatch):
        monkeypatch.setenv("agentic_ui_allowed_users", '["someone@redhat.com"]')
        monkeypatch.setenv("ENGINEER_OVERRIDE", "someone@redhat.com")

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 200
        upstream.assert_called_once()


class TestUpstreamFailures:
    def test_connection_error_maps_to_502(self, client, upstream):
        upstream.side_effect = requests.ConnectionError()

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 502
        assert resp.get_json() == {"error": "AI Agents service unavailable"}

    def test_timeout_maps_to_504(self, client, upstream):
        upstream.side_effect = requests.Timeout()

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 504
        assert resp.get_json() == {"error": "AI Agents service timeout"}

    def test_other_request_errors_map_to_502(self, client, upstream):
        upstream.side_effect = requests.exceptions.InvalidURL()

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 502

    def test_non_json_error_page_keeps_status_and_returns_json(self, client, upstream):
        # e.g. an OpenShift router 503 HTML page during a pod restart
        upstream.return_value = make_response(503, json_error=True)

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 503
        assert resp.get_json() == {"error": "AI Agents service error (HTTP 503)"}

    def test_non_json_success_is_reported_as_bad_gateway(self, client, upstream):
        upstream.return_value = make_response(200, json_error=True)

        resp = client.get("/api/ai/status/task-1")

        assert resp.status_code == 502


class TestInputValidation:
    @pytest.mark.parametrize("case_number", ["1234567", "123456789", "abcdefgh"])
    def test_rejects_invalid_case_numbers(self, client, upstream, case_number):
        assert client.get(f"/api/ai/report/case/{case_number}").status_code == 400
        assert client.post(f"/api/ai/analyze/{case_number}").status_code == 400
        upstream.assert_not_called()

    @pytest.mark.parametrize(
        "path",
        [
            "/api/ai/status/..",
            "/api/ai/status/a.b",
            "/api/ai/logs/%2e%2e",
            "/api/ai/feedback/x%3Fy",
            "/api/ai/status/" + "a" * 129,
        ],
    )
    def test_rejects_unsafe_ids(self, client, upstream, path):
        assert client.get(path).status_code == 400
        upstream.assert_not_called()

    @pytest.mark.parametrize("ident", ["0b6f6c1e-8d2a-4c1e-9f7e-1a2b3c4d5e6f", "42"])
    def test_accepts_uuid_and_integer_ids(self, client, upstream, ident):
        assert client.get(f"/api/ai/logs/{ident}").status_code == 200

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"json": ["not", "an", "object"]},
            {"data": "nope", "content_type": "text/plain"},
        ],
    )
    def test_feedback_post_requires_json_object(self, client, upstream, kwargs):
        resp = client.post("/api/ai/feedback/abc", **kwargs)

        assert resp.status_code == 400
        upstream.assert_not_called()
