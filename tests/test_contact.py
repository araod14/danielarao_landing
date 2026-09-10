import smtplib
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from api import main

PAYLOAD = {"name": "Jane Doe", "email": "jane@example.com", "message": "I need clinic data in a CSV file."}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "limiter", main.RateLimiter())
    monkeypatch.delenv("TRUSTED_PROXY_CIDR", raising=False)
    with TestClient(main.app) as client:
        yield client


def test_delivery_happens_before_success(client, monkeypatch):
    send = MagicMock()
    monkeypatch.setattr(main, "send_email", send)
    result = client.post("/api/contact", json=PAYLOAD)
    assert result.status_code == 200
    assert result.json() == {"status": "sent"}
    assert send.call_args[0][0].email == "jane@example.com"


@pytest.mark.parametrize("field,value", [("name", " "), ("email", "invalid"), ("message", "short"), ("message", "x" * 5001), ("name", "Jane\r\nBcc: evil@example.com")])
def test_invalid_payload_never_sends(client, monkeypatch, field, value):
    send = MagicMock()
    monkeypatch.setattr(main, "send_email", send)
    assert client.post("/api/contact", json={**PAYLOAD, field: value}).status_code == 422
    send.assert_not_called()


def test_rate_limit_and_untrusted_forwarding(client, monkeypatch):
    monkeypatch.setattr(main, "send_email", MagicMock())
    for n in range(5):
        assert client.post("/api/contact", json=PAYLOAD, headers={"X-Real-IP": f"203.0.113.{n}"}).status_code == 200
    result = client.post("/api/contact", json=PAYLOAD, headers={"X-Forwarded-For": "203.0.113.99"})
    assert result.status_code == 429
    assert int(result.headers["retry-after"]) > 0


def test_trusted_proxy_separates_clients(monkeypatch):
    monkeypatch.setattr(main, "limiter", main.RateLimiter(limit=1))
    monkeypatch.setenv("TRUSTED_PROXY_CIDR", "172.30.14.2/32")
    monkeypatch.setattr(main, "send_email", MagicMock())
    with TestClient(main.app, client=("172.30.14.2", 50000)) as client:
        assert client.post("/api/contact", json=PAYLOAD, headers={"X-Real-IP": "203.0.113.1"}).status_code == 200
        assert client.post("/api/contact", json=PAYLOAD, headers={"X-Real-IP": "203.0.113.1"}).status_code == 429
        assert client.post("/api/contact", json=PAYLOAD, headers={"X-Real-IP": "203.0.113.2"}).status_code == 200


def test_smtp_failure_does_not_claim_success(client, monkeypatch):
    monkeypatch.setattr(main, "send_email", MagicMock(side_effect=smtplib.SMTPException("secret")))
    result = client.post("/api/contact", json=PAYLOAD)
    assert result.status_code == 503
    assert "secret" not in result.text


def test_missing_settings_degrades(client, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert client.post("/api/contact", json=PAYLOAD).status_code == 503
    assert client.get("/api/health").status_code == 200


def test_window_expiry_and_capacity(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: now[0])
    limiter = main.RateLimiter(limit=1, window=10, max_ips=1)
    assert limiter.allow("first")[0]
    assert not limiter.allow("first")[0]
    assert not limiter.allow("second")[0]
    now[0] += 11
    assert limiter.allow("second")[0]
    assert len(limiter.entries) == 1


def test_smtp_tls_and_reply_to(monkeypatch):
    for key, value in {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "user", "SMTP_PASSWORD": "password", "SMTP_FROM": "sender@example.com", "SMTP_TO": "daniel@example.com", "SMTP_SECURITY": "starttls"}.items():
        monkeypatch.setenv(key, value)
    smtp = MagicMock()
    smtp.send_message.return_value = {}
    transport = MagicMock()
    transport.__enter__.return_value = smtp
    monkeypatch.setattr(main.smtplib, "SMTP", MagicMock(return_value=transport))
    main.send_email(main.Contact(**PAYLOAD))
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user", "password")
    message = smtp.send_message.call_args[0][0]
    assert message["From"] == "sender@example.com"
    assert message["Reply-To"] == PAYLOAD["email"]
    assert PAYLOAD["message"] in message.get_content()
