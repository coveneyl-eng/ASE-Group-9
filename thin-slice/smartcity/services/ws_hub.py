"""WebSocket hub (FastAPI): pushes live Kafka updates to the officials' portal without page refresh.
    uvicorn smartcity.services.ws_hub:app --port 8003
"""
import asyncio
import threading

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from smartcity import bus, config, secrets, telemetry

t = telemetry.setup("websocket-hub")
JWT_SECRET = secrets.get_secret("jwt-signing-key", config.JWT_SECRET)
TOPICS = ["flood.impacts", "flood.forecast", "traffic.reroute", "traffic.signals", "event.plans",
          "event.transport", "notifications.sent", "dispatch.approved"]
stopping = threading.Event()  # set on shutdown so the Kafka consumer leaves its group cleanly
app = FastAPI(title="WebSocket hub")
clients: set[WebSocket] = set()
latest: dict[str, dict] = {}
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
    if loop:
        asyncio.run_coroutine_threadsafe(broadcast(payload), loop)


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
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=config.JWT_ISSUER)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"topic": "hello", "data": {"user": claims["sub"], "role": claims["role"]}})
    for payload in latest.values():
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
def health():
    return {"status": "ok", "clients": len(clients), "topics_seen": sorted(latest)}


@app.get("/state")
def state():
    """Public status map data (no auth): current flood extent and impacts only."""
    return {k: v for k, v in latest.items() if k in ("flood.impacts", "flood.forecast")}
