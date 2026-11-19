"""WebSocket hub (FastAPI): pushes live Kafka updates to the officials' portal without page refresh, and serves
the system-health dashboard (component probes, topic activity, latency, test-flood trigger).
    uvicorn smartcity.services.ws_hub:app --port 8003
"""
import asyncio
import threading
import time

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from smartcity import bus, config, secrets, telemetry
from smartcity.services import health

t = telemetry.setup("websocket-hub")
JWT_SECRET = secrets.get_secret("jwt-signing-key", config.JWT_SECRET)
TOPICS = ["flood.readings", "flood.events", "flood.forecast", "flood.impacts", "traffic.flow", "traffic.congestion",
          "traffic.signals", "traffic.reroute", "event.upcoming", "event.watch", "event.plans", "event.transport",
          "dispatch.approved", "notifications.sent"]
REPLAY_ON_CONNECT = {"flood.impacts", "flood.forecast", "traffic.reroute", "event.plans", "dispatch.approved"}
CAN_SIMULATE = {"emergency_responder"}
STATUS_CACHE_S = 3.0

stopping = threading.Event()  # set on shutdown so the Kafka consumer leaves its group cleanly
app = FastAPI(title="WebSocket hub")
clients: set[WebSocket] = set()
latest: dict[str, dict] = {}
activity: dict[str, dict] = {topic: {"count": 0, "last": None} for topic in TOPICS}
_status_cache: dict = {"at": 0.0, "body": None}
_status_lock = threading.Lock()
loop: asyncio.AbstractEventLoop | None = None


async def broadcast(payload: dict) -> None:
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception:
            clients.discard(ws)


def handle(topic: str, msg) -> None:
    payload = {"topic": topic, "data": msg.model_dump(mode="json")}
    latest[topic] = payload
    activity[topic]["count"] += 1
    activity[topic]["last"] = time.time()
    if loop:
        asyncio.run_coroutine_threadsafe(broadcast(payload), loop)


def decode(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=config.JWT_ISSUER)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc


def current_user(authorization: str = Header("")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return decode(authorization[7:])


@app.on_event("startup")
async def start():
    global loop
    loop = asyncio.get_running_loop()
    consumer_thread = threading.Thread(target=bus.consume, args=("websocket-hub", TOPICS, handle, stopping.is_set),
                                       daemon=True)
    consumer_thread.start()
    app.state.consumer_thread = consumer_thread


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = ""):
    try:
        claims = decode(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"topic": "hello", "data": {"user": claims["sub"], "role": claims["role"]}})
    for topic, payload in latest.items():
        if topic in REPLAY_ON_CONNECT:
            await ws.send_json(payload)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


@app.on_event("shutdown")
def stop_consumer():
    stopping.set()
    app.state.consumer_thread.join(timeout=5)  # let consumer.close() leave the group before exit


@app.get("/health")
def health_check():
    return {"status": "ok", "clients": len(clients), "topics_seen": sorted(t for t, a in activity.items() if a["count"])}


@app.get("/state")
def state():
    """Public status map data (no auth): current flood extent and impacts only."""
    return {k: v for k, v in latest.items() if k in ("flood.impacts", "flood.forecast")}


@app.get("/status")
def status(user: dict = Depends(current_user)):
    """System-health dashboard: every component probed in parallel (cached briefly), topic activity, latency."""
    with _status_lock:
        if _status_cache["body"] is None or time.time() - _status_cache["at"] > STATUS_CACHE_S:
            checks = health.run_all(f"{len(clients)} live clients, {len(TOPICS)} topics subscribed")
            _status_cache["body"] = {"checks": checks, "latency": health.latency_stats()}
            _status_cache["at"] = time.time()
    now = time.time()
    topics = [{"topic": tp, "count": a["count"], "seconds_ago": None if a["last"] is None else round(now - a["last"])}
              for tp, a in activity.items()]
    return {**_status_cache["body"], "topics": topics, "generated_at": now}


class FloodTest(BaseModel):
    level_m: float = Field(3.2, ge=0, le=10)


@app.post("/simulate-flood")
def simulate_flood(req: FloodTest, user: dict = Depends(current_user)):
    """Publish one above-threshold reading on the field MQTT broker, exactly as a sensor would."""
    if user["role"] not in CAN_SIMULATE:
        raise HTTPException(403, f"role {user['role']} cannot trigger test readings")
    from smartcity.simulators import sensors
    client = sensors.connect()
    try:
        payload = sensors.reading(sensors.SENSORS[0], req.level_m)
        sensors.publish(client, payload)
    finally:
        client.loop_stop()
        client.disconnect()
    t["log"].info("%s sent test flood reading %.2f m (trace %s)", user["sub"], req.level_m, payload["trace_id"])
    return {"trace_id": payload["trace_id"], "sensor_id": payload["sensor_id"], "level_m": req.level_m,
            "observed_at": payload["observed_at"]}
