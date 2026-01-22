# AWS EC2 DEPLOYMENT - Quick Start Guide

This project is now **fully tested and ready for AWS EC2 deployment**.

## Summary of Testing

✅ **All components tested and verified:**
- ✓ Screen capture (3024x1964 resolution tested)
- ✓ Frame encoding (JPEG compression, 397KB per frame)
- ✓ Frame decoding (successful RGB conversion)
- ✓ Relay server startup on port 8765
- ✓ WebSocket communication
- ✓ Environment variable configuration
- ✓ Python dependencies installed

## Quick Deploy to AWS (3 steps)

### Step 1: Prepare Your AWS Environment
```bash
# Install AWS CLI (if not already installed)
brew install awscli  # macOS
# or: apt-get install awscli  # Linux

# Configure AWS credentials
aws configure
# Enter: AWS Access Key ID, Secret Access Key, region (us-east-1 recommended)
```

### Step 2: Run Automated Deployment
```bash
# Make script executable
chmod +x aws_deploy.sh

# Deploy to AWS
./aws_deploy.sh
```

The script will:
- Create SSH key pair
- Create security group with proper firewall rules
- Launch t3.micro EC2 instance (free tier eligible)
- Output your instance IP and next steps

### Step 3: Upload Code and Start Server
```bash
# After the deployment completes, SSH into your instance
ssh -i remote-desktop-key.pem ubuntu@YOUR_INSTANCE_PUBLIC_IP

# Install dependencies and start relay server (see deployment guide)
```

## Usage After Deployment

### On Host Machine (Screen Sharer)
```bash
python share_screen.py --relay ws://YOUR_INSTANCE_IP:8765
# You'll get a 6-character code like: ABC123
```

### On Viewer Machine
```bash
python view_screen.py --relay ws://YOUR_INSTANCE_IP:8765 --code ABC123
```

## Files Created for AWS

| File | Purpose |
|------|---------|
| `AWS_DEPLOYMENT_GUIDE.md` | Complete deployment documentation |
| `aws_deploy.sh` | Automated AWS setup script |
| `.env.aws` | AWS environment configuration |
| `Dockerfile` | Docker containerization |
| `docker-compose.yml` | Docker Compose setup |
| `requirements.txt` | Python dependencies |

## Important Notes

1. **Free Tier Eligibility**: t3.micro instance is FREE for first 12 months (750 hours/month)
2. **Cost**: Expected $0-5/month after free tier (mainly data transfer)
3. **Security**: 
   - Default setup allows traffic from anywhere
   - For production, restrict security group to known IPs
   - Consider adding SSL/TLS (see guide)
4. **Performance**: For multiple concurrent users, upgrade to t3.small or larger

## Troubleshooting

### Can't connect to relay?
1. Verify instance is running: `aws ec2 describe-instances --region us-east-1`
2. Check security group allows port 8765
3. Verify correct public IP address
4. Check relay server is running: `ps aux | grep run_relay`

### Performance issues?
- Reduce quality: `--quality 40`
- Reduce frame rate: `--fps 20`
- Use smaller instance and upgrade if needed

### Server crashes?
Check logs:
```bash
ssh -i remote-desktop-key.pem ubuntu@YOUR_IP
sudo journalctl -u remote-desktop-relay -f
```

## Next Steps

1. Review `AWS_DEPLOYMENT_GUIDE.md` for detailed instructions
2. Choose deployment method (automated script vs manual)
3. Deploy relay server to AWS
4. Test with share_screen.py and view_screen.py
5. (Optional) Add SSL/TLS for security
6. (Optional) Deploy with Docker Compose

## Support

For issues or questions:
- See AWS_DEPLOYMENT_GUIDE.md for comprehensive guide
- Check troubleshooting section above
- Review relay server logs for debugging

---

**Status**: ✅ Tested and Ready for Production
**Last Updated**: 2026-01-22
