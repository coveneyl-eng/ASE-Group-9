"""Send email messages through the Gmail API."""

import base64
import os
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, Optional, Union

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
DEFAULT_TOKEN_FILE = Path(__file__).with_name("token.json")


def _validate_email_address(address: str, field_name: str) -> None:
    if (
        not isinstance(address, str)
        or not address
        or "\r" in address
        or "\n" in address
    ):
        raise ValueError(f"{field_name} must be a valid email address")

    parsed_address = parseaddr(address)[1]
    if not parsed_address or parsed_address.count("@") != 1:
        raise ValueError(f"{field_name} must be a valid email address")

    local_part, domain = parsed_address.rsplit("@", 1)
    if (
        not local_part
        or not domain
        or "." not in domain
        or any(character.isspace() for character in parsed_address)
    ):
        raise ValueError(f"{field_name} must be a valid email address")


def _get_credentials(
    client_secret_file: Union[str, Path],
    token_file: Union[str, Path],
) -> Credentials:
    secret_path = Path(client_secret_file).expanduser()
    token_path = Path(token_file).expanduser()
    if not secret_path.is_file():
        raise ValueError(
            "The Gmail OAuth client-secret file was not found; "
            "check GMAIL_CLIENT_SECRET_FILE"
        )

    credentials = None
    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(token_path), SCOPES
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secret_path), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_descriptor = os.open(
            token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(token_descriptor, "w", encoding="utf-8") as token_file:
            token_path.chmod(0o600)
            token_file.write(credentials.to_json())

    return credentials


def send_email(
    recipient: str,
    subject: str,
    body: str,
    sender: Optional[str] = None,
    client_secret_file: Optional[Union[str, Path]] = None,
    token_file: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Send a plain-text email and return Gmail's message resource."""
    _validate_email_address(recipient, "recipient")
    if not isinstance(subject, str):
        raise ValueError("subject must be a string")
    if not subject.strip() or "\r" in subject or "\n" in subject:
        raise ValueError("subject must not be empty or contain line breaks")
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    if sender is not None:
        _validate_email_address(sender, "sender")

    secret_file = (
        client_secret_file
        or os.getenv("GMAIL_CLIENT_SECRET_FILE")
    )
    if not secret_file:
        raise ValueError(
            "Set the GMAIL_CLIENT_SECRET_FILE environment variable"
        )

    credentials = _get_credentials(
        secret_file, token_file or DEFAULT_TOKEN_FILE
    )
    service = build(
        "gmail", "v1", credentials=credentials, cache_discovery=False
    )

    message = MIMEText(body, "plain", "utf-8")
    message["to"] = recipient
    if sender is not None:
        message["from"] = sender
    message["subject"] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    response = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw_message})
        .execute()
    )
    if not isinstance(response, dict):
        raise RuntimeError("Gmail API returned an unexpected response format")
    return response
