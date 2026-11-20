"""Notification Agent (FastAPI): decides who is told what, sends SMS (SMSAPI) / email (Gmail API) through the
team's clients in APIs/notification, and logs sensor-to-alert latency.

Providers run in dry-run mode until SMSAPI_TOKEN / GMAIL_CLIENT_SECRET_FILE are set, so the demo never spams.
    uvicorn smartcity.services.notification:app --port 8001
"""
import functools
import threading

from fastapi import FastAPI

from smartcity import bus, config, db, team_apis, telemetry
from smartcity.models import DispatchApproval, FloodForecast, FloodImpact, NotificationSent, RerouteCommand, now

t = telemetry.setup("notification-agent")


@functools.cache
def publisher() -> bus.Publisher:
    return bus.Publisher()


@functools.cache
def conn():
    return db.connect()


stopping = threading.Event()  # set on shutdown so the Kafka consumer leaves its group cleanly
app = FastAPI(title="Notification Agent")


def send_sms(to: str, text: str) -> tuple[bool, bool]:
    """APIs/notification/SMSapi.send_sms. SMSAPI test mode unless SMS_LIVE=1; dry-run without a token."""
    sms = team_apis.load("SMSapi") if config.SMSAPI_TOKEN else None
    if sms is None:
        t["log"].info("[dry-run SMS] to %s: %s", to, text)
        return True, True
    sms.send_sms(phone_number=to, message=text, test_mode=not config.SMS_LIVE, token=config.SMSAPI_TOKEN)
    return True, not config.SMS_LIVE


def send_email(to: str, subject: str, body: str) -> tuple[bool, bool]:
    """APIs/notification/Emailapi.send_email (Gmail API); dry-run until GMAIL_CLIENT_SECRET_FILE is set."""
    mail = team_apis.load("Emailapi") if config.GMAIL_CLIENT_SECRET_FILE else None
    if mail is None:
        t["log"].info("[dry-run Gmail] to %s: %s", to, subject)
        return True, True
    mail.send_email(recipient=to, subject=subject, body=body, client_secret_file=config.GMAIL_CLIENT_SECRET_FILE,
                    token_file=config.GMAIL_TOKEN_FILE)
    return True, False


def record(trace_id: str, channel: str, to: str, text: str, observed_at, result: tuple[bool, bool]) -> None:
    latency_ms = (now() - observed_at).total_seconds() * 1000
    delivered, dry_run = result
    conn().execute("INSERT INTO notifications (trace_id, channel, recipient, text, latency_ms, delivered, dry_run) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (trace_id, channel, to, text, latency_ms, delivered, dry_run))
    t["latency"].record(latency_ms / 1000, {"channel": channel})
    publisher().publish("notifications.sent", NotificationSent(trace_id=trace_id, channel=channel, recipient=to,
                                                             text=text, latency_ms=latency_ms, delivered=delivered,
                                                             dry_run=dry_run))
    t["log"].info("%s to %s in %.0f ms (trace %s)", channel, to, latency_ms, trace_id)


def handle(topic: str, msg) -> None:
    if isinstance(msg, FloodImpact):
        unsafe = [i.name for i in msg.impacts if i.status == "unsafe"]
        if not unsafe:
            return
        sms = f"FLOOD WARNING near {msg.sensor_id}. Avoid: {', '.join(unsafe)}. Move to higher ground."
        record(msg.trace_id, "sms", config.NOTIFY_SMS_TO, sms, msg.observed_at, send_sms(config.NOTIFY_SMS_TO, sms))
        body = f"Flood impact {msg.id}: unsafe assets {unsafe}. Approve dispatch in the officials' portal."
        record(msg.trace_id, "email", config.NOTIFY_EMAIL_TO, body, msg.observed_at,
               send_email(config.NOTIFY_EMAIL_TO, "Flood impact - approval needed", body))
    elif isinstance(msg, DispatchApproval):
        body = f"{msg.action} approved by {msg.approved_by} ({msg.role}) for impact {msg.impact_id}."
        record(msg.trace_id, "email", config.NOTIFY_EMAIL_TO, body, msg.created_at,
               send_email(config.NOTIFY_EMAIL_TO, "Dispatch approved", body))
    elif isinstance(msg, RerouteCommand):
        t["log"].info("drivers informed of reroute via edges %s", msg.path_edges)
    elif isinstance(msg, FloodForecast) and msg.expected_impact == "major":
        t["log"].info("forecast warning queued for authorities: %.2f m", msg.predicted_level_m)


@app.on_event("startup")
def start_consumer():
    topics = ["flood.impacts", "dispatch.approved", "traffic.reroute", "flood.forecast"]
    consumer_thread = threading.Thread(target=bus.consume, args=("notification-agent", topics, handle, stopping.is_set),
                                       daemon=True)
    consumer_thread.start()
    app.state.consumer_thread = consumer_thread


@app.on_event("shutdown")
def stop_consumer():
    stopping.set()
    app.state.consumer_thread.join(timeout=5)  # let consumer.close() leave the group before exit


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/notifications/recent")
def recent(limit: int = 20):
    return conn().execute("SELECT at, trace_id, channel, recipient, text, latency_ms, dry_run FROM notifications "
                        "ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
