# AWS Deployment Guide for Remote Desktop Relay Server

## Quick Start

### Prerequisites
- AWS Account with free tier access
- AWS CLI installed and configured
- SSH client (macOS/Linux: native, Windows: PuTTY or WSL)
- Your Remote Desktop project files

### Option 1: Automated Deployment (Recommended)

```bash
# Make deployment script executable
chmod +x aws_deploy.sh

# Run the deployment script
./aws_deploy.sh
```

The script will:
1. Create/reuse SSH key pair
2. Create security group with proper firewall rules
3. Launch t3.micro instance (free tier eligible)
4. Configure network access
5. Provide instance details and next steps

### Option 2: Manual Deployment

#### Step 1: Create EC2 Instance

1. Go to AWS EC2 Dashboard
2. Click "Launch Instances"
3. Choose Ubuntu 22.04 LTS AMI
4. Instance type: `t3.micro` (free tier eligible)
5. Network settings:
   - VPC: Default
   - Auto-assign public IP: Enable
6. Security group (create new):
   - Inbound rules:
     - SSH (22): 0.0.0.0/0
     - TCP (8765): 0.0.0.0/0 (Relay server port)
7. Create new key pair and download .pem file
8. Launch instance

#### Step 2: Connect to Instance

```bash
# Set permissions on key file
chmod 400 your-key.pem

# SSH into instance
ssh -i your-key.pem ubuntu@YOUR_INSTANCE_PUBLIC_IP
```

#### Step 3: Setup Remote Desktop

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install dependencies
sudo apt-get install -y python3-pip python3-venv git

# Create app directory
sudo mkdir -p /opt/remote-desktop
sudo chown ubuntu:ubuntu /opt/remote-desktop
cd /opt/remote-desktop

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip
pip install websockets Pillow numpy

# Copy your project files to /opt/remote-desktop
# Use SCP from your local machine:
# scp -i your-key.pem -r . ubuntu@YOUR_IP:/opt/remote-desktop/
```

#### Step 4: Start Relay Server

**Option A: Direct Execution (Testing)**
```bash
cd /opt/remote-desktop
source venv/bin/activate
python run_relay.py --host 0.0.0.0 --port 8765
```

**Option B: Background with nohup**
```bash
cd /opt/remote-desktop
source venv/bin/activate
nohup python run_relay.py --host 0.0.0.0 --port 8765 > relay.log 2>&1 &
```

**Option C: Systemd Service (Recommended)**

Create `/etc/systemd/system/remote-desktop-relay.service`:
```ini
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
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable remote-desktop-relay
sudo systemctl start remote-desktop-relay

# Check status
sudo systemctl status remote-desktop-relay

# View logs
sudo journalctl -u remote-desktop-relay -f
```

## Using the Relay Server

### For Screen Sharing (Host)

```bash
python share_screen.py --relay ws://YOUR_INSTANCE_PUBLIC_IP:8765
```

The host will receive a 6-character session code to share.

### For Viewing (Client)

```bash
python view_screen.py --relay ws://YOUR_INSTANCE_PUBLIC_IP:8765 --code ABC123
```

## Performance Optimization

### For AWS EC2

1. **Instance Type Selection**:
   - `t3.micro`: Free tier, suitable for 1-2 concurrent sessions
   - `t3.small`: For 3-5 concurrent sessions
   - `t3.medium`: For 5-10 concurrent sessions
   - `c5.large`: High performance, compute-optimized

2. **Quality Settings** (on host machine):
   ```bash
   # Low bandwidth (slower but uses less data)
   python share_screen.py --relay ws://IP:8765 --quality 40 --fps 20
   
   # Balanced
   python share_screen.py --relay ws://IP:8765 --quality 60 --fps 24
   
   # High quality (requires good bandwidth)
   python share_screen.py --relay ws://IP:8765 --quality 80 --fps 30
   ```

3. **Bandwidth Monitoring**:
   - Monitor data transfer in AWS CloudWatch
   - Free tier: 1 GB/month free data transfer
   - Typical usage: 50-200 MB per 1-hour session

## Security Considerations

⚠️ **Before Production Deployment:**

1. **Change Default Port**: Modify port 8765 to a non-standard port
2. **Add Authentication**: Implement user authentication/authorization
3. **Use HTTPS/WSS**: Enable SSL/TLS certificate
   ```bash
   # Install certbot for Let's Encrypt
   sudo apt-get install certbot python3-certbot-nginx
   sudo certbot certonly --standalone -d your-domain.com
   ```
4. **Firewall Rules**: Restrict relay port to known IP ranges
5. **Regular Updates**: Keep system packages updated
6. **Monitor Logs**: Set up CloudWatch alarms for errors

### Example: WSS (Secure WebSocket)

1. Get SSL certificate from Let's Encrypt
2. Modify `relay/server.py` to use SSL context:

```python
import ssl

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(
    certfile="/path/to/cert.pem",
    keyfile="/path/to/key.pem"
)

async with serve(
    self._handle_connection,
    self.host,
    self.port,
    ssl=ssl_context
):
    # ...
```

Then use `wss://` URLs instead of `ws://`.

## Troubleshooting

### Server won't start
```bash
# Check if port is in use
sudo netstat -tuln | grep 8765

# Check logs
sudo journalctl -u remote-desktop-relay -e

# Try different port
python run_relay.py --port 9000
```

### Can't connect from outside
1. Verify security group allows inbound on port 8765
2. Check firewall: `sudo ufw status`
3. Verify public IP is correct
4. Test connectivity: `telnet YOUR_IP 8765`

### High latency
1. Choose instance closer to users (different region)
2. Check network performance: `mtr YOUR_IP`
3. Reduce frame rate: `--fps 15`
4. Lower quality: `--quality 40`

### Memory issues
```bash
# Check memory usage
free -h

# Monitor relay server memory
ps aux | grep run_relay.py

# Increase swap if needed
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

## Cost Estimation (Monthly)

For **free tier** (if eligible):
- EC2 t3.micro instance: FREE (750 hours/month)
- Data transfer: 1 GB free, $0.09/GB after
- Estimated cost: **$0 - $5/month** (if within free tier)

For **paid** t3.small:
- Instance: ~$8/month
- Data transfer: $0.09/GB
- Estimated cost: **$10-20/month** (depending on usage)

## Monitoring & Logs

```bash
# View relay server stats
curl http://YOUR_IP:8765/stats  # Not implemented yet

# Monitor in real-time
watch -n 1 'ps aux | grep run_relay.py'

# Check disk space
df -h

# Check EC2 CloudWatch
# AWS Console > CloudWatch > Dashboards > EC2
```

## Scaling for Multiple Users

For production with many users:

1. **Load Balancing**: Use AWS Load Balancer to distribute traffic
2. **Multiple Instances**: Deploy relay on multiple EC2 instances
3. **Database**: Store session info in DynamoDB for persistence
4. **Message Queue**: Use SQS for better reliability
5. **Monitoring**: Enable CloudWatch alarms and dashboards

## Cleanup

To stop and remove resources:

```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-xxxxx --region us-east-1

# Terminate instance
aws ec2 terminate-instances --instance-ids i-xxxxx --region us-east-1

# Delete security group (after instance is terminated)
aws ec2 delete-security-group --group-id sg-xxxxx --region us-east-1

# Delete key pair
aws ec2 delete-key-pair --key-name remote-desktop-key --region us-east-1
```

## Support & Resources

- **AWS Documentation**: https://docs.aws.amazon.com/ec2/
- **WebSocket Guide**: https://websockets.readthedocs.io/
- **Remote Desktop Project**: https://github.com/17lohith/Remote-Desktop
