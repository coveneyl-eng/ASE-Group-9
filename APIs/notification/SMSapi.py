"""Send SMS messages through the SMSAPI HTTP API."""

import os
import re
from typing import Any, Dict, Optional

import requests

API_URL = "https://api.smsapi.com/sms.do"
PHONE_NUMBER_PATTERN = re.compile(r"\+?[1-9]\d{7,14}")


def send_sms(
    phone_number: str,
    message: str,
    sender: Optional[str] = None,
    test_mode: bool = True,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Send an SMS and return the decoded SMSAPI response."""
    if not isinstance(phone_number, str):
        raise ValueError("phone_number must be a string")
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    if not isinstance(test_mode, bool):
        raise ValueError("test_mode must be a boolean")
    if sender is not None and not isinstance(sender, str):
        raise ValueError("sender must be a string")

    normalized_number = phone_number.strip()
    if not PHONE_NUMBER_PATTERN.fullmatch(normalized_number):
        raise ValueError(
            "phone_number must be an international number with 8 to 15 digits"
        )
    if not message or not message.strip():
        raise ValueError("message must not be empty")

    api_token = token or os.getenv("SMSAPI_TOKEN")
    if not isinstance(api_token, str) or not api_token.strip():
        raise ValueError("Set the SMSAPI_TOKEN environment variable")

    form_data = {
        "to": normalized_number.lstrip("+"),
        "message": message,
        "format": "json",
        "test": "1" if test_mode else "0",
    }
    if sender and sender.strip():
        form_data["from"] = sender.strip()

    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_token}"},
            data=form_data,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"SMSAPI request failed: {exc}") from exc

    if not response.ok:
        raise RuntimeError(f"SMSAPI returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "SMSAPI returned a response that was not valid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError("SMSAPI returned an unexpected response format")
    if payload.get("error"):
        error_message = payload.get("message", "No error message provided")
        raise RuntimeError(
            "SMSAPI rejected the request "
            f"(code {payload['error']}): {error_message}"
        )
    if not isinstance(payload.get("list"), list) or not payload["list"]:
        raise RuntimeError("SMSAPI response did not contain a message list")
    if any(not isinstance(item, dict) for item in payload["list"]):
        raise RuntimeError("SMSAPI returned an invalid message entry")

    return payload

