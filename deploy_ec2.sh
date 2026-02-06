#!/bin/bash
# =================================================================
# Remote Desktop Relay Server - AWS EC2 Deployment Script
# =================================================================
#
# This script sets up the relay server on a fresh EC2 instance.
#
# Prerequisites:
#   - Ubuntu 22.04 or Amazon Linux 2023 EC2 instance
#   - SSH access to the instance
#   - Security group with port 8765 open (TCP inbound)
#
# Usage:
#   1. Launch EC2 instance (t3.micro is sufficient)
#   2. SSH into the instance
#   3. Copy this project to the instance
#   4. Run: chmod +x deploy_ec2.sh && ./deploy_ec2.sh
#
# =================================================================

set -e

echo "==========================================="
echo " Remote Desktop - Relay Server Deployment"
echo "==========================================="
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    OS="unknown"
fi

echo "Detected OS: $OS"
echo ""

# -------------------------------------------------------------------
# Step 1: Install system dependencies
# -------------------------------------------------------------------
echo "[1/5] Installing system dependencies..."

if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv git
elif [ "$OS" = "amzn" ]; then
    sudo yum update -y -q
    sudo yum install -y -q python3 python3-pip git
else
    echo "Warning: Unknown OS. Please ensure Python 3.8+ is installed."
fi

echo "  Python version: $(python3 --version)"
echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 2: Set up Python virtual environment
# -------------------------------------------------------------------
echo "[2/5] Setting up Python environment..."

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip -q
pip install websockets>=12.0 -q

echo "  Virtual environment: $INSTALL_DIR/venv"
echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 3: Verify the relay server works
# -------------------------------------------------------------------
echo "[3/5] Verifying relay server..."

python3 -c "
import sys
sys.path.insert(0, '.')
from relay.server import RelayServer, RelayMessageType, generate_session_code
code = generate_session_code()
print(f'  Module imports: OK')
print(f'  Session code generation: {code}')
print(f'  RelayServer class: OK')
"

echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 4: Create systemd service
# -------------------------------------------------------------------
echo "[4/5] Creating systemd service..."

SERVICE_FILE="/etc/systemd/system/remote-desktop-relay.service"

sudo tee $SERVICE_FILE > /dev/null << EOF
[Unit]
Description=Remote Desktop Relay Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/run_relay.py --host 0.0.0.0 --port 8765
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable remote-desktop-relay

echo "  Service file: $SERVICE_FILE"
echo "  Done."
echo ""

# -------------------------------------------------------------------
# Step 5: Start the service
# -------------------------------------------------------------------
echo "[5/5] Starting relay server..."

sudo systemctl start remote-desktop-relay
sleep 2

# Check if running
if sudo systemctl is-active --quiet remote-desktop-relay; then
    echo "  Status: RUNNING"
else
    echo "  Status: FAILED"
    echo "  Check logs: sudo journalctl -u remote-desktop-relay -f"
    exit 1
fi

# Get public IP
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "YOUR_EC2_PUBLIC_IP")

echo ""
echo "==========================================="
echo " Deployment Complete!"
echo "==========================================="
echo ""
echo " Relay server is running on port 8765"
echo ""
echo " Your relay URL:"
echo ""
echo "   ws://${PUBLIC_IP}:8765"
echo ""
echo " To share your screen:"
echo "   python share_screen.py --relay ws://${PUBLIC_IP}:8765"
echo ""
echo " To view a remote screen:"
echo "   python view_screen.py --relay ws://${PUBLIC_IP}:8765 --code <CODE>"
echo ""
echo " Useful commands:"
echo "   sudo systemctl status remote-desktop-relay"
echo "   sudo systemctl restart remote-desktop-relay"
echo "   sudo journalctl -u remote-desktop-relay -f"
echo ""
echo " IMPORTANT: Make sure your EC2 Security Group"
echo " has port 8765 open for TCP inbound traffic!"
echo "==========================================="
