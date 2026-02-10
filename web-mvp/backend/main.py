"""
Remote Desktop – Web MVP Backend

FastAPI server that manages session codes and points clients
to the relay server.

Run:
    uvicorn main:app --reload --port 8000
"""

import os
import time
import secrets
import string
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Change this ONE variable when you move to EC2.
# Locally  : ws://127.0.0.1:8765
# On EC2   : ws://<EC2_PUBLIC_IP>:8765
RELAY_URL = os.environ.get("RELAY_URL", "ws://127.0.0.1:8765")

SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL", "600"))  # 10 min default

# ---------------------------------------------------------------------------
# In-memory session store  (swap for Redis / DB later)
# ---------------------------------------------------------------------------

sessions: dict[str, dict] = {}
#  code -> {
#      "code": "AB3XY7",
#      "role": "host",          # who created it
#      "relay_url": "ws://...",
#      "created_at": 1234567890.0,
#      "status": "waiting" | "connected" | "closed",
#      "host_connected": True/False,
#      "client_connected": True/False,
#  }


def _generate_code(length: int = 6) -> str:
    """6-char alphanumeric, no confusing chars (0/O/I/1/L)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if code not in sessions:
            return code


def _cleanup_expired() -> None:
    """Remove sessions older than TTL."""
    now = time.time()
    expired = [c for c, s in sessions.items()
               if now - s["created_at"] > SESSION_TTL_SECONDS]
    for c in expired:
        del sessions[c]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateSessionResponse(BaseModel):
    code: str
    relay_url: str
    status: str
    message: str


class JoinRequest(BaseModel):
    code: str


class JoinResponse(BaseModel):
    code: str
    relay_url: str
    status: str
    message: str


class SessionStatus(BaseModel):
    code: str
    status: str
    relay_url: str
    created_at: float
    host_connected: bool
    client_connected: bool


class HealthResponse(BaseModel):
    status: str
    relay_url: str
    active_sessions: int


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Remote Desktop – Web MVP",
    version="1.0.0",
    description="Session management API for the Remote Desktop relay system.",
)

# CORS – allow the frontend (served on a different port) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
def health():
    """Health-check endpoint."""
    _cleanup_expired()
    return HealthResponse(
        status="ok",
        relay_url=RELAY_URL,
        active_sessions=len(sessions),
    )


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session():
    """
    Create a new session.
    Returns a 6-digit code the host shares with the viewer.
    """
    _cleanup_expired()

    code = _generate_code()
    sessions[code] = {
        "code": code,
        "relay_url": RELAY_URL,
        "created_at": time.time(),
        "status": "waiting",
        "host_connected": False,
        "client_connected": False,
    }

    return CreateSessionResponse(
        code=code,
        relay_url=RELAY_URL,
        status="waiting",
        message=f"Session created. Share code {code} with the viewer.",
    )


@app.post("/api/sessions/join", response_model=JoinResponse)
def join_session(body: JoinRequest):
    """
    Join an existing session with a code.
    Returns the relay URL for the viewer to connect.
    """
    _cleanup_expired()

    code = body.code.upper().strip()

    if len(code) != 6:
        raise HTTPException(status_code=400, detail="Session code must be 6 characters.")

    session = sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {code} not found or expired.")

    if session["status"] == "closed":
        raise HTTPException(status_code=410, detail="Session has ended.")

    session["status"] = "connected"
    session["client_connected"] = True

    return JoinResponse(
        code=code,
        relay_url=session["relay_url"],
        status="connected",
        message="Joined session. Connect to the relay URL to start viewing.",
    )


@app.get("/api/sessions/{code}", response_model=SessionStatus)
def get_session(code: str):
    """Check the status of a session."""
    _cleanup_expired()

    code = code.upper().strip()
    session = sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    return SessionStatus(
        code=session["code"],
        status=session["status"],
        relay_url=session["relay_url"],
        created_at=session["created_at"],
        host_connected=session["host_connected"],
        client_connected=session["client_connected"],
    )


@app.delete("/api/sessions/{code}")
def close_session(code: str):
    """Close / end a session."""
    code = code.upper().strip()
    session = sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    session["status"] = "closed"
    return {"message": f"Session {code} closed."}
