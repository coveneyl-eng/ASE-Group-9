"""Approval Service (FastAPI): OAuth2 password flow issuing JWTs, role-checked sign-off, audit log, Blob report.
    uvicorn smartcity.services.approval:app --port 8002
"""
import functools
import json
from datetime import timedelta

import jwt
from azure.storage.blob import BlobServiceClient
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from smartcity import bus, config, db, secrets, telemetry
from smartcity.models import DispatchApproval, now

t = telemetry.setup("approval-service")
JWT_SECRET = secrets.get_secret("jwt-signing-key", config.JWT_SECRET)


@functools.cache
def publisher() -> bus.Publisher:
    return bus.Publisher()


@functools.cache
def conn():
    return db.connect()


oauth2 = OAuth2PasswordBearer(tokenUrl="token")
app = FastAPI(title="Approval Service")

# Demo identities only. Production uses Entra ID (OAuth2) behind NGINX; roles come from token claims.
USERS = {
    "dispatcher": {"password": "dispatch-demo", "role": "emergency_responder"},
    "planner": {"password": "planner-demo", "role": "transport_planner"},
}
CAN_APPROVE = {"dispatch_responders": {"emergency_responder"}, "close_roads": {"emergency_responder", "transport_planner"},
               "reject": {"emergency_responder", "transport_planner"}}


def issue_token(username: str, role: str) -> str:
    claims = {"sub": username, "role": role, "iss": config.JWT_ISSUER, "exp": now() + timedelta(minutes=15)}
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def current_user(token: str = Depends(oauth2)) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=config.JWT_ISSUER)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc


class ApprovalRequest(BaseModel):
    impact_id: str
    trace_id: str = ""
    action: str
    confirm: bool  # explicit confirmation required for dispatch/approval actions


@app.post("/token")
def token(form: OAuth2PasswordRequestForm = Depends()):
    user = USERS.get(form.username)
    if not user or user["password"] != form.password:
        raise HTTPException(401, "bad credentials")
    return {"access_token": issue_token(form.username, user["role"]), "token_type": "bearer", "role": user["role"]}


@app.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@app.post("/approvals")
def approve(req: ApprovalRequest, user: dict = Depends(current_user)):
    if req.action not in CAN_APPROVE:
        raise HTTPException(400, "unknown action")
    if user["role"] not in CAN_APPROVE[req.action]:  # roles checked again on every approval (QoS doc)
        raise HTTPException(403, f"role {user['role']} cannot {req.action}")
    if not req.confirm:
        raise HTTPException(400, "explicit confirmation required")
    report = {"impact_id": req.impact_id, "action": req.action, "by": user["sub"], "role": user["role"],
              "at": now().isoformat()}
    blob_name = f"approvals/{req.impact_id}-{req.action}.json"
    blob = BlobServiceClient.from_connection_string(config.BLOB_CONNECTION_STRING)
    container = blob.get_container_client(config.BLOB_CONTAINER)
    if not container.exists():
        container.create_container()
    container.upload_blob(blob_name, json.dumps(report), overwrite=True)
    conn().execute("INSERT INTO audit_log (actor, role, action, payload) VALUES (%s, %s, %s, %s)",
                 (user["sub"], user["role"], req.action, json.dumps(report)))
    msg = DispatchApproval(impact_id=req.impact_id, action=req.action, approved_by=user["sub"], role=user["role"],
                           report_blob=blob_name, **({"trace_id": req.trace_id} if req.trace_id else {}))
    publisher().publish("dispatch.approved", msg)
    t["log"].info("%s approved %s for %s", user["sub"], req.action, req.impact_id)
    return {"status": "approved", "report_blob": blob_name, "message_id": msg.id}


@app.get("/audit")
def audit(user: dict = Depends(current_user), limit: int = 20):
    return conn().execute("SELECT at, actor, role, action, payload FROM audit_log ORDER BY id DESC LIMIT %s",
                        (limit,)).fetchall()


@app.get("/health")
def health():
    return {"status": "ok"}
