# Dockerfile for Remote Desktop Relay Server

FROM python:3.11-slim

WORKDIR /app

# Only install what the relay server needs
RUN pip install --no-cache-dir websockets>=12.0

# Copy only the files the relay server needs
COPY common/ ./common/
COPY relay/ ./relay/
COPY run_relay.py .

# Expose port
EXPOSE 8765

# Health check - simple TCP connection test
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost', 8765)); s.close()" || exit 1

# Run relay server
CMD ["python", "run_relay.py", "--host", "0.0.0.0", "--port", "8765"]
