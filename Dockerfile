# Dockerfile for Remote Desktop Relay Server

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import asyncio; asyncio.run(__import__('websockets').connect('ws://localhost:8765'))" || exit 1

# Run relay server
CMD ["python", "run_relay.py", "--host", "0.0.0.0", "--port", "8765"]
