#!/bin/bash
# =================================================================
# Remote Desktop Relay Server - AWS EC2 Docker Deployment
# =================================================================
#
# Prerequisites:
#   - Ubuntu 22.04 / Amazon Linux 2023 EC2 instance (t3.micro is fine)
#   - SSH access
#   - Security Group: port 8765 TCP inbound open
#
# Usage:
#   1. SSH into EC2
#   2. Clone or scp this project
#   3. chmod +x deploy_ec2.sh && ./deploy_ec2.sh
#
# =================================================================

set -euo pipefail

echo "==========================================="
echo " Remote Desktop Relay - EC2 Docker Deploy"
echo "==========================================="
echo ""

# -------------------------------------------------------------------
# 1. Install Docker if missing
# -------------------------------------------------------------------
echo "[1/4] Checking Docker..."

if command -v docker &> /dev/null; then
    echo "  Docker already installed: $(docker --version)"
else
    echo "  Installing Docker..."

    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        OS="unknown"
    fi

    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq docker.io
    elif [ "$OS" = "amzn" ]; then
        sudo yum install -y -q docker
    else
        echo "  Unknown OS – please install Docker manually."
        exit 1
    fi

    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out/in for group to take effect."
    echo "  Continuing with sudo for now..."
fi
echo ""

# Decide whether we need sudo for docker commands
DOCKER_CMD="docker"
if ! docker info &>/dev/null 2>&1; then
    DOCKER_CMD="sudo docker"
fi

# -------------------------------------------------------------------
# 2. Build the image
# -------------------------------------------------------------------
echo "[2/4] Building Docker image..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

$DOCKER_CMD build -t rd-relay .
echo "  Image built: rd-relay"
echo "  Image size: $($DOCKER_CMD images rd-relay --format '{{.Size}}')"
echo ""

# -------------------------------------------------------------------
# 3. Run the container
# -------------------------------------------------------------------
echo "[3/4] Starting container..."

# Stop old container if exists
$DOCKER_CMD rm -f rd-relay 2>/dev/null || true

$DOCKER_CMD run -d \
    --name rd-relay \
    --restart unless-stopped \
    -p 8765:8765 \
    rd-relay

sleep 2

# Verify it's running
if $DOCKER_CMD ps --filter name=rd-relay --format '{{.Status}}' | grep -q "Up"; then
    echo "  Container: RUNNING"
else
    echo "  Container: FAILED"
    echo "  Logs:"
    $DOCKER_CMD logs rd-relay
    exit 1
fi
echo ""

# -------------------------------------------------------------------
# 4. Verify connectivity
# -------------------------------------------------------------------
echo "[4/4] Verifying relay is reachable..."

# TCP check from host
if python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',8765)); s.close()" 2>/dev/null; then
    echo "  localhost:8765 -> OK"
elif python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',8765)); s.close()" 2>/dev/null; then
    echo "  localhost:8765 -> OK"
else
    echo "  WARNING: Could not verify port locally (python may not be installed on host)."
    echo "  Container logs:"
    $DOCKER_CMD logs --tail 5 rd-relay
fi

# Get public IP (EC2 metadata endpoint)
PUBLIC_IP=$(curl -s --connect-timeout 3 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<YOUR_EC2_PUBLIC_IP>")

echo ""
echo "==========================================="
echo " DEPLOYMENT COMPLETE"
echo "==========================================="
echo ""
echo " Container : rd-relay"
echo " Status    : $($DOCKER_CMD ps --filter name=rd-relay --format '{{.Status}}')"
echo " Port      : 8765"
echo ""
echo " Your relay URL:"
echo ""
echo "   ws://${PUBLIC_IP}:8765"
echo ""
echo " -------------------------------------------"
echo " FROM YOUR LOCAL MACHINE:"
echo ""
echo "   # Share your screen"
echo "   python share_screen.py --relay ws://${PUBLIC_IP}:8765"
echo ""
echo "   # View a remote screen"
echo "   python view_screen.py --relay ws://${PUBLIC_IP}:8765 --code <CODE>"
echo ""
echo " -------------------------------------------"
echo " CONTAINER MANAGEMENT:"
echo ""
echo "   docker logs -f rd-relay          # live logs"
echo "   docker restart rd-relay          # restart"
echo "   docker stop rd-relay             # stop"
echo "   docker start rd-relay            # start again"
echo ""
echo " IMPORTANT: Ensure your EC2 Security Group"
echo " has port 8765 open for TCP inbound traffic."
echo "==========================================="
