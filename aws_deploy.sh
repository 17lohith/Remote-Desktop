#!/bin/bash
# AWS EC2 Deployment Script for Remote Desktop Relay Server

set -e

# Configuration
INSTANCE_NAME="remote-desktop-relay"
INSTANCE_TYPE="t3.micro"  # Free tier eligible
REGION="us-east-1"
KEY_NAME="remote-desktop-key"  # Change to your key pair name
PORT="8765"

echo "=================================="
echo "Remote Desktop - AWS EC2 Setup"
echo "=================================="

# Step 1: Create SSH key pair (if not exists)
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" 2>/dev/null; then
    echo "Creating SSH key pair: $KEY_NAME"
    aws ec2 create-key-pair --key-name "$KEY_NAME" --region "$REGION" > "$KEY_NAME.pem"
    chmod 400 "$KEY_NAME.pem"
    echo "✓ Key saved to $KEY_NAME.pem"
else
    echo "✓ Key pair $KEY_NAME already exists"
fi

# Step 2: Get default VPC and subnet
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --region "$REGION" --query "Vpcs[0].VpcId" --output text)
SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --region "$REGION" --query "Subnets[0].SubnetId" --output text)

echo "Using VPC: $VPC_ID"
echo "Using Subnet: $SUBNET_ID"

# Step 3: Create security group
SECURITY_GROUP_NAME="remote-desktop-sg"
SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SECURITY_GROUP_NAME" --region "$REGION" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
    echo "Creating security group: $SECURITY_GROUP_NAME"
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SECURITY_GROUP_NAME" \
        --description "Security group for Remote Desktop Relay Server" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query "GroupId" \
        --output text)
    
    # Allow SSH
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp \
        --port 22 \
        --cidr 0.0.0.0/0 \
        --region "$REGION"
    
    # Allow relay server port (WebSocket)
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp \
        --port "$PORT" \
        --cidr 0.0.0.0/0 \
        --region "$REGION"
    
    echo "✓ Security group created: $SG_ID"
else
    echo "✓ Security group already exists: $SG_ID"
fi

# Step 4: Get latest Ubuntu 22.04 LTS AMI
AMI_ID=$(aws ec2 describe-images \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
    --region "$REGION" \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" \
    --output text)

echo "Using AMI: $AMI_ID"

# Step 5: Create user data script for initialization
cat > /tmp/user_data.sh << 'EOF'
#!/bin/bash
set -e

# Update system
apt-get update
apt-get upgrade -y

# Install Python and dependencies
apt-get install -y \
    python3-pip \
    python3-venv \
    git \
    curl

# Create app directory
mkdir -p /opt/remote-desktop
cd /opt/remote-desktop

# Clone repository (or upload files)
# For initial setup, you can manually upload the code or use git
# git clone https://github.com/17lohith/Remote-Desktop.git .

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install websockets Pillow numpy

# Create systemd service for relay server
cat > /etc/systemd/system/remote-desktop-relay.service << 'SYSTEMD'
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

# Enable and start the service (after files are uploaded)
# systemctl daemon-reload
# systemctl enable remote-desktop-relay
# systemctl start remote-desktop-relay

echo "EC2 initialization complete"
EOF

chmod +x /tmp/user_data.sh

# Step 6: Launch instance
echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --subnet-id "$SUBNET_ID" \
    --user-data file:///tmp/user_data.sh \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --region "$REGION" \
    --query "Instances[0].InstanceId" \
    --output text)

echo "✓ Instance launched: $INSTANCE_ID"
echo ""
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query "Reservations[0].Instances[0].PublicIpAddress" \
    --output text)

echo "✓ Instance public IP: $PUBLIC_IP"
echo ""
echo "=================================="
echo "Next Steps:"
echo "=================================="
echo "1. Wait 2-3 minutes for instance to be ready"
echo "2. SSH into instance:"
echo "   ssh -i $KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo ""
echo "3. Upload project files:"
echo "   scp -i $KEY_NAME.pem -r . ubuntu@$PUBLIC_IP:/opt/remote-desktop/"
echo ""
echo "4. Start the relay server:"
echo "   ssh -i $KEY_NAME.pem ubuntu@$PUBLIC_IP 'sudo systemctl start remote-desktop-relay'"
echo ""
echo "5. Use relay server URL:"
echo "   ws://$PUBLIC_IP:$PORT"
echo ""
echo "Hosts and viewers can now connect using:"
echo "   python share_screen.py --relay ws://$PUBLIC_IP:$PORT"
echo "   python view_screen.py --relay ws://$PUBLIC_IP:$PORT --code ABC123"
echo "=================================="
