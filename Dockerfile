# ---- Remote Desktop Relay Server ----
# Lightweight, production-ready image.
# Only ships the relay server (no GUI, no screen-capture code).

FROM python:3.11-slim AS base

# Labels
LABEL maintainer="Remote Desktop Project"
LABEL description="Relay server for cross-network remote desktop connections"

# No .pyc files, unbuffered stdout so logs appear in docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ---- Dependencies ----
# The relay server only needs the websockets library.
COPY requirements-relay.txt .
RUN pip install --no-cache-dir -r requirements-relay.txt

# ---- Application code ----
# Copy ONLY what the relay server imports:
#   run_relay.py  ->  relay/server.py  ->  common/protocol.py
#                                      ->  common/config.py  (loaded but not critical)
COPY common/__init__.py  common/__init__.py
COPY common/protocol.py  common/protocol.py
COPY common/config.py    common/config.py
COPY relay/__init__.py   relay/__init__.py
COPY relay/server.py     relay/server.py
COPY run_relay.py        run_relay.py

# ---- Runtime ----
EXPOSE 8765

# Healthcheck: plain TCP connect – fast, no extra deps.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',8765)); s.close()"

# The relay server binds 0.0.0.0 so it is reachable outside the container.
ENTRYPOINT ["python", "run_relay.py"]
CMD ["--host", "0.0.0.0", "--port", "8765"]
