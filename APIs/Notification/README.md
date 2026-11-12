# Notification APIs

This folder contains standalone SMSAPI and Gmail API clients. API credentials
can be supplied through environment variables; messages are sent only by
calling the functions with message content as arguments. The modules do not
send messages when run or imported.

## Setup

Use Python 3.8 or newer, create and activate a virtual environment, and install
the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`.

Run the API tests from this folder:

```bash
python -m pytest
```

Tests mock the SMS and Gmail services and do not send real messages.

## SMS

Set only the SMSAPI access token in the environment. Pass the recipient,
message, sender, and test/live choice to the function:

```bash
export SMSAPI_TOKEN="your-smsapi-token"
```

```python
from SMSapi import send_sms

result = send_sms(
    phone_number="+353851234567",
    message="Your customized message",
    sender="Example",
    test_mode=True,
)
```

Test mode is enabled by default. Set `test_mode=False` only when you intend to
send a real SMS.

## Gmail

In Google Cloud Console, enable the Gmail API and create OAuth client
credentials for a desktop application. Store the downloaded OAuth client
configuration outside version control.

```bash
export GMAIL_CLIENT_SECRET_FILE="/path/to/client_secret.json"
```

The first run opens a browser for Google authorization. The refreshable
authorization token is saved to `token.json` beside `Emailapi.py` by default.
Pass a different token file using the `token_file` function argument. The
application requests only the Gmail send scope.

Pass recipient, subject, body, and optional sender as function arguments:

```python
from Emailapi import send_email

result = send_email(
    recipient="recipient@example.com",
    subject="Example subject",
    body="Your customized message",
    sender="sender@example.com",
)
```

Both `send_email` and `send_sms` can be called repeatedly with different
content without changing environment configuration.

## Credentials and safety

Do not commit API tokens, OAuth client-secret JSON files, authorization token
files, or `.env` files. The local `.gitignore` excludes the common credential
files. If a credential was previously committed or shared, revoke or rotate it
with its provider before using the scripts.

Both clients validate the required input and surface API or network failures.
They do not log access tokens or message bodies.
