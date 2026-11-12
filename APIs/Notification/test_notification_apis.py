"""Tests for the SMSAPI and Gmail notification clients."""

import base64
from email import message_from_bytes
from unittest.mock import Mock

import pytest

import Emailapi
import SMSapi


def test_send_sms_posts_message_and_returns_response(monkeypatch):
    response_payload = {
        "list": [{"id": "sms-123", "number": "353851234567", "status": "OK"}]
    }
    response = Mock(ok=True, status_code=200)
    response.json.return_value = response_payload
    post = Mock(return_value=response)
    monkeypatch.setattr(SMSapi.requests, "post", post)

    result = SMSapi.send_sms(
        "+353851234567",
        "Custom SMS",
        sender="Example",
        token="test-token",
    )

    assert result == response_payload
    post.assert_called_once()
    request = post.call_args.kwargs
    assert post.call_args.args[0] == SMSapi.API_URL
    assert request["data"] == {
        "to": "353851234567",
        "message": "Custom SMS",
        "format": "json",
        "test": "1",
        "from": "Example",
    }
    assert request["headers"]["Authorization"]
    assert request["timeout"] == 30


def test_send_sms_uses_environment_token_and_live_mode(monkeypatch):
    monkeypatch.setenv("SMSAPI_TOKEN", "environment-token")
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"list": [{"id": "sms-123"}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(SMSapi.requests, "post", post)

    SMSapi.send_sms("353851234567", "Live message", test_mode=False)

    assert post.call_args.kwargs["headers"]["Authorization"]
    assert post.call_args.kwargs["data"]["test"] == "0"


@pytest.mark.parametrize(
    ("phone_number", "message", "token", "error"),
    [
        ("invalid", "Message", "token", "phone_number"),
        ("353851234567", " ", "token", "message"),
        ("353851234567", "Message", "", "SMSAPI_TOKEN"),
        (None, "Message", "token", "phone_number"),
    ],
)
def test_send_sms_rejects_invalid_input(
    phone_number, message, token, error
):
    with pytest.raises(ValueError, match=error):
        SMSapi.send_sms(phone_number, message, token=token)


def test_send_sms_reports_http_failure(monkeypatch):
    response = Mock(ok=False, status_code=401)
    post = Mock(return_value=response)
    monkeypatch.setattr(SMSapi.requests, "post", post)

    with pytest.raises(RuntimeError, match="HTTP 401"):
        SMSapi.send_sms("353851234567", "Message", token="test-token")


def test_send_sms_reports_provider_error(monkeypatch):
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"error": 13, "message": "Invalid recipient"}
    monkeypatch.setattr(SMSapi.requests, "post", Mock(return_value=response))

    with pytest.raises(RuntimeError, match="Invalid recipient"):
        SMSapi.send_sms("353851234567", "Message", token="test-token")


def test_send_sms_reports_network_failure(monkeypatch):
    monkeypatch.setattr(
        SMSapi.requests,
        "post",
        Mock(side_effect=SMSapi.requests.RequestException("offline")),
    )

    with pytest.raises(RuntimeError, match="request failed"):
        SMSapi.send_sms("353851234567", "Message", token="test-token")


def test_send_email_builds_and_sends_message(monkeypatch, tmp_path):
    credentials = object()
    monkeypatch.setattr(
        Emailapi, "_get_credentials", Mock(return_value=credentials)
    )
    execute = Mock(return_value={"id": "gmail-123"})
    send = Mock()
    send.return_value.execute = execute
    service = Mock()
    service.users.return_value.messages.return_value.send = send
    build = Mock(return_value=service)
    monkeypatch.setattr(Emailapi, "build", build)

    result = Emailapi.send_email(
        recipient="recipient@example.com",
        subject="Custom subject",
        body="Custom body",
        sender="sender@example.com",
        client_secret_file=tmp_path / "client_secret.json",
        token_file=tmp_path / "token.json",
    )

    assert result == {"id": "gmail-123"}
    Emailapi._get_credentials.assert_called_once_with(
        tmp_path / "client_secret.json",
        tmp_path / "token.json",
    )
    build.assert_called_once_with(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )
    send.assert_called_once()
    assert send.call_args.kwargs["userId"] == "me"

    raw_message = send.call_args.kwargs["body"]["raw"]
    decoded_message = base64.urlsafe_b64decode(raw_message.encode("ascii"))
    message = message_from_bytes(decoded_message)
    assert message["To"] == "recipient@example.com"
    assert message["From"] == "sender@example.com"
    assert message["Subject"] == "Custom subject"
    assert message.get_payload(decode=True) == b"Custom body"


def test_send_email_reads_only_oauth_secret_path_from_environment(
    monkeypatch, tmp_path
):
    secret_file = tmp_path / "client_secret.json"
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setattr(
        Emailapi, "_get_credentials", Mock(return_value=object())
    )
    service = Mock()
    messages = service.users.return_value.messages
    send = messages.return_value.send
    execute = send.return_value.execute
    execute.return_value = {
        "id": "gmail-123"
    }
    monkeypatch.setattr(Emailapi, "build", Mock(return_value=service))

    Emailapi.send_email("recipient@example.com", "Subject", "Body")

    Emailapi._get_credentials.assert_called_once_with(
        str(secret_file), Emailapi.DEFAULT_TOKEN_FILE
    )


@pytest.mark.parametrize(
    ("recipient", "subject", "body", "error"),
    [
        ("not-an-email", "Subject", "Body", "recipient"),
        ("recipient@example.com", " ", "Body", "subject"),
        ("recipient@example.com", "Bad\nsubject", "Body", "subject"),
        ("recipient@example.com", "Subject", None, "body"),
    ],
)
def test_send_email_rejects_invalid_input(recipient, subject, body, error):
    with pytest.raises(ValueError, match=error):
        Emailapi.send_email(
            recipient,
            subject,
            body,
            client_secret_file="client_secret.json",
        )


def test_send_email_requires_oauth_secret_file(monkeypatch):
    monkeypatch.delenv("GMAIL_CLIENT_SECRET_FILE", raising=False)

    with pytest.raises(ValueError, match="GMAIL_CLIENT_SECRET_FILE"):
        Emailapi.send_email("recipient@example.com", "Subject", "Body")


def test_send_email_rejects_unexpected_provider_response(monkeypatch):
    monkeypatch.setattr(
        Emailapi, "_get_credentials", Mock(return_value=object())
    )
    service = Mock()
    messages = service.users.return_value.messages
    send = messages.return_value.send
    send.return_value.execute.return_value = None
    monkeypatch.setattr(Emailapi, "build", Mock(return_value=service))

    with pytest.raises(RuntimeError, match="unexpected response"):
        Emailapi.send_email(
            "recipient@example.com",
            "Subject",
            "Body",
            client_secret_file="client_secret.json",
        )
