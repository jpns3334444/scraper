#!/bin/bash
set -e
exec > >(tee -a /var/log/user-data.log) 2>&1

# Configuration
OUTPUT_BUCKET="${OUTPUT_BUCKET:-tokyo-real-estate-ai-data}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
GITHUB_REPO="https://github.com/jpns3334444/scraper.git"
GITHUB_BRANCH="master"
MAX_RETRIES=5

echo "=== Starting EC2 initialization at $(date) ==="
echo "Configuration:"
echo "  - OUTPUT_BUCKET: $OUTPUT_BUCKET"
echo "  - AWS_REGION: $AWS_REGION"
echo "  - GitHub Repo: $GITHUB_REPO"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/scraper/run.log
}

# Create log directory
mkdir -p /var/log/scraper/
touch /var/log/scraper/run.log
chown ubuntu:ubuntu /var/log/scraper/run.log

# Update and install dependencies
log "Installing system packages..."
apt-get update -y
apt-get install -y \
    python3-pip \
    unzip \
    wget \
    curl \
    gnupg \
    software-properties-common \
    git \
    awscli

# Set environment variables
log "Setting environment variables..."
echo "export OUTPUT_BUCKET=\"$OUTPUT_BUCKET\"" >> /etc/environment
echo "export OUTPUT_BUCKET=\"$OUTPUT_BUCKET\"" >> /home/ubuntu/.bashrc

# Install CloudWatch Agent
log "Installing CloudWatch Agent..."
wget -q https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
dpkg -i amazon-cloudwatch-agent.deb
rm amazon-cloudwatch-agent.deb

# Configure CloudWatch Agent
log "Configuring CloudWatch Agent..."
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc/
cat > /opt/aws/amazon-cloudwatch-agent/etc/config.json << 'EOF'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/scraper/run.log",
            "log_group_name": "scraper-logs",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
EOF

# Install Python dependencies
log "Installing Python dependencies..."
pip3 install --upgrade pip
pip3 install --upgrade \
    pandas \
    requests \
    beautifulsoup4 \
    boto3 \
    lxml \
    Pillow

# Retrieve GitHub token from Secrets Manager (optional)
log "Retrieving GitHub token from Secrets Manager..."
GITHUB_TOKEN=$(aws secretsmanager get-secret-value \
    --secret-id github-token \
    --region "$AWS_REGION" \
    --query SecretString \
    --output text 2>/dev/null || echo "")

# Clone repository with retries
log "Cloning repository from GitHub..."
for i in $(seq 1 $MAX_RETRIES); do
    log "Attempt $i of $MAX_RETRIES..."
    
    # Construct GitHub URL with optional token
    if [ -n "$GITHUB_TOKEN" ]; then
        CLONE_URL="https://${GITHUB_TOKEN}@github.com/jpns3334444/scraper.git"
    else
        CLONE_URL="$GITHUB_REPO"
    fi
    
    # Try to clone
    if git clone -b "$GITHUB_BRANCH" "$CLONE_URL" /tmp/scraper-repo; then
        log "Successfully cloned repository on attempt $i"
        
        # Copy scraper script
        cp /tmp/scraper-repo/scrape.py /home/ubuntu/scrape.py
        rm -rf /tmp/scraper-repo
        
        # Set permissions
        chmod +x /home/ubuntu/scrape.py
        chown ubuntu:ubuntu /home/ubuntu/scrape.py
        
        log "scrape.py successfully installed"
        log "File size: $(ls -lh /home/ubuntu/scrape.py | awk '{print $5}')"
        break
    else
        log "Failed to clone repository on attempt $i"
        if [ $i -eq $MAX_RETRIES ]; then
            log "ERROR: All clone attempts failed!"
            log "Please check GitHub repository: $GITHUB_REPO"
            exit 1
        fi
        sleep 5
    fi
done

# Verify Python dependencies
log "Testing Python dependencies..."
if python3 -c 'import pandas, requests, boto3, bs4; print("All dependencies OK")' >> /var/log/scraper/run.log 2>&1; then
    log "All Python dependencies verified"
else
    log "WARNING: Python dependency check failed"
fi

# Start CloudWatch Agent
log "Starting CloudWatch Agent..."
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
    -a fetch-config \
    -m ec2 \
    -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json \
    -s

# Enable and start SSM Agent
log "Starting SSM Agent..."
systemctl enable amazon-ssm-agent
systemctl start amazon-ssm-agent

# Final status check
log "=== INITIALIZATION SUMMARY ==="
log "Instance ID: $(curl -s http://169.254.169.254/latest/meta-data/instance-id)"
log "Available disk space: $(df -h / | tail -1 | awk '{print $4}')"
log "Python version: $(python3 --version)"
log "AWS CLI version: $(aws --version)"
log "OUTPUT_BUCKET: $OUTPUT_BUCKET"
log "Scraper script: $([ -f /home/ubuntu/scrape.py ] && echo 'Installed' || echo 'Not found')"
log "=== END SUMMARY ==="

log "EC2 initialization completed successfully at $(date)"