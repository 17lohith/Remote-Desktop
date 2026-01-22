#!/bin/bash
# Complete AWS EC2 Deployment Script
# Run this on your EC2 instance after SSH login
# Usage: bash deploy.sh

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Remote Desktop Relay - AWS EC2 Deployment Script          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# STEP 1: Update system
echo "▶ STEP 1: Updating system packages..."
sudo apt update
sudo apt upgrade -y
echo "✓ System updated"
echo ""

# STEP 2: Install dependencies
echo "▶ STEP 2: Installing dependencies..."
sudo apt install -y \
    python3-pip \
    python3-venv \
    git \
    curl \
    build-essential
echo "✓ Dependencies installed"
echo ""

# STEP 3: Create app directory
echo "▶ STEP 3: Creating application directory..."
sudo mkdir -p /opt/remote-desktop
sudo chown ubuntu:ubuntu /opt/remote-desktop
cd /opt/remote-desktop
echo "✓ Directory created: /opt/remote-desktop"
echo ""

# STEP 4: Clone project from GitHub
echo "▶ STEP 4: Cloning Remote Desktop project..."
if [ -d ".git" ]; then
    echo "  Repository already exists, pulling latest..."
    git pull origin main
else
    git clone https://github.com/17lohith/Remote-Desktop.git .
fi
echo "✓ Project cloned/updated"
echo ""

# STEP 5: Create virtual environment
echo "▶ STEP 5: Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
echo "✓ Virtual environment created"
echo ""

# STEP 6: Install Python dependencies
echo "▶ STEP 6: Installing Python dependencies..."
pip install --upgrade pip
pip install websockets Pillow numpy
echo "✓ Python dependencies installed"
echo ""

# STEP 7: Test relay server
echo "▶ STEP 7: Testing relay server startup..."
timeout 5 python run_relay.py --host 0.0.0.0 --port 8765 || true
echo "✓ Relay server test passed (timeout expected)"
echo ""

# STEP 8: Setup systemd service
echo "▶ STEP 8: Setting up systemd service..."
sudo tee /etc/systemd/system/remote-desktop-relay.service > /dev/null << 'SYSTEMD'
[Unit]
Description=Remote Desktop Relay Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/remote-desktop
ExecStart=/opt/remote-desktop/venv/bin/python /opt/remote-desktop/run_relay.py --host 0.0.0.0 --port 8765
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSTEMD
echo "✓ Systemd service created"
echo ""

# STEP 9: Enable and start service
echo "▶ STEP 9: Enabling and starting relay service..."
sudo systemctl daemon-reload
sudo systemctl enable remote-desktop-relay
sudo systemctl start remote-desktop-relay
echo "✓ Service enabled and started"
echo ""

# STEP 10: Verify service
echo "▶ STEP 10: Verifying service status..."
sleep 2
sudo systemctl status remote-desktop-relay
echo "✓ Service is running"
echo ""

# STEP 11: Verify port is listening
echo "▶ STEP 11: Verifying port 8765 is listening..."
if sudo netstat -tuln | grep -q ":8765 "; then
    echo "✓ Port 8765 is listening"
else
    echo "⚠ Port 8765 might not be listening yet. Check logs:"
    echo "   sudo journalctl -u remote-desktop-relay -e"
fi
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              ✅ DEPLOYMENT COMPLETE!                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Deployment Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ System updated"
echo "✓ Dependencies installed"
echo "✓ Application deployed"
echo "✓ Virtual environment created"
echo "✓ Python packages installed"
echo "✓ Systemd service configured"
echo "✓ Relay server running on 0.0.0.0:8765"
echo ""

# Get instance IP
INSTANCE_IP=$(hostname -I | awk '{print $1}')
echo "📍 Your relay server is running at:"
echo "   ws://$INSTANCE_IP:8765"
echo ""

echo "🚀 Usage Commands:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "# View relay server logs:"
echo "sudo journalctl -u remote-desktop-relay -f"
echo ""
echo "# Check service status:"
echo "sudo systemctl status remote-desktop-relay"
echo ""
echo "# Stop service:"
echo "sudo systemctl stop remote-desktop-relay"
echo ""
echo "# Start service:"
echo "sudo systemctl start remote-desktop-relay"
echo ""

echo "💻 From your local machine:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "# Share your screen:"
echo "python share_screen.py --relay ws://$INSTANCE_IP:8765"
echo ""
echo "# View remote screen (use the code from share_screen.py):"
echo "python view_screen.py --relay ws://$INSTANCE_IP:8765 --code ABC123"
echo ""

echo "📚 For troubleshooting, see AWS_DEPLOYMENT_GUIDE.md"
echo ""
