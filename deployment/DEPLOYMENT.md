# Trading Dashboard - Deployment Guide

## Quick Reference

### Local Development
```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
python main.py

# Terminal 2: Frontend
cd frontend
npm start
```

### Docker Deployment
```bash
docker-compose up -d
```

---

## Detailed Deployment Instructions

### 1. DigitalOcean App Platform (Recommended for Simplicity)

#### Step 1: Prepare GitHub
```bash
git init
git remote add origin https://github.com/yourname/trading-dashboard.git
git add .
git commit -m "Initial commit: trading dashboard"
git push -u origin main
```

#### Step 2: Create DigitalOcean App

1. Go to https://cloud.digitalocean.com/apps
2. Click "Create App" → "GitHub" → Select your repo
3. Configure:
   - **Backend Service**
     - Source: `./backend` directory
     - Build: `pip install -r requirements.txt`
     - Run: `python main.py`
     - HTTP Port: 8000
   
   - **Frontend Service**
     - Source: `./frontend` directory
     - Build: `npm install && npm run build`
     - Run: `npx serve -s build -l 5000`
     - HTTP Port: 5000

4. Add environment variables:
   ```
   FINNHUB_API_KEY=<your-api-key>
   REDIS_URL=redis://default:password@redis:6379/0
   ```

5. Add Redis database from marketplace
6. Deploy!

**Cost**: ~$12-15/month (free tier available with limits)
**Uptime**: 99.99% SLA
**Auto-scaling**: Available

---

### 2. AWS EC2 with Docker

#### Step 1: Launch EC2 Instance
```bash
# t2.medium recommended (2GB RAM)
# Ubuntu 22.04 LTS
# Security group: Allow ports 22, 80, 443, 8000
```

#### Step 2: SSH and Setup
```bash
ssh -i your-key.pem ubuntu@your-instance-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add current user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### Step 3: Deploy
```bash
# Clone repository
git clone https://github.com/yourname/trading-dashboard.git
cd trading-dashboard

# Create .env file
cat > .env << EOF
FINNHUB_API_KEY=your_api_key_here
TELEGRAM_BOT_TOKEN=optional
TELEGRAM_CHAT_ID=optional
EOF

# Start services
docker-compose up -d

# View logs
docker-compose logs -f backend
```

#### Step 4: Setup Nginx Reverse Proxy
```bash
sudo apt install nginx

# Create Nginx config
sudo cp nginx.conf /etc/nginx/nginx.conf

# Generate self-signed SSL (or use Let's Encrypt)
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/key.pem \
  -out /etc/nginx/ssl/cert.pem

sudo systemctl restart nginx
```

**Cost**: $6-12/month
**Uptime**: 99.95% (depends on region)
**Storage**: 20GB EBS included

---

### 3. Traditional VPS (Linode, Hetzner, etc.)

#### Step 1: Server Setup
```bash
# SSH into server
ssh root@your-vps-ip

# Create trading user
useradd -m -s /bin/bash trading
su - trading

# Install dependencies
sudo apt update && sudo apt install -y \
  python3.11 python3-pip python3-venv \
  nodejs npm \
  redis-server \
  nginx \
  git \
  curl \
  wget

# Clone repository
git clone https://github.com/yourname/trading-dashboard.git
cd trading-dashboard
```

#### Step 2: Backend Setup
```bash
cd backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env
cp .env.example .env
nano .env  # Edit with your API keys

# Test run
python main.py
# Should see "Uvicorn running on http://0.0.0.0:8000"
```

#### Step 3: Frontend Setup
```bash
cd ../frontend

# Install and build
npm install
npm run build

# Test run
npx serve -s build -l 5000
# Should see frontend running on http://localhost:5000
```

#### Step 4: Systemd Services

**Backend Service** (`/etc/systemd/system/trading-dashboard-backend.service`)
```ini
[Unit]
Description=Trading Dashboard Backend
After=network.target redis-server.service

[Service]
Type=simple
User=trading
WorkingDirectory=/home/trading/trading-dashboard/backend
Environment="PATH=/home/trading/trading-dashboard/backend/venv/bin"
Environment="FINNHUB_API_KEY=your_key"
Environment="REDIS_URL=redis://localhost:6379/0"
ExecStart=/home/trading/trading-dashboard/backend/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Frontend Service** (`/etc/systemd/system/trading-dashboard-frontend.service`)
```ini
[Unit]
Description=Trading Dashboard Frontend
After=network.target

[Service]
Type=simple
User=trading
WorkingDirectory=/home/trading/trading-dashboard/frontend
ExecStart=/usr/bin/npx serve -s build -l 5000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-dashboard-backend
sudo systemctl enable trading-dashboard-frontend
sudo systemctl start trading-dashboard-backend
sudo systemctl start trading-dashboard-frontend

# Check status
sudo systemctl status trading-dashboard-backend
```

#### Step 5: Nginx Configuration
```bash
# Backup original
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

# Use provided config
sudo cp nginx.conf /etc/nginx/nginx.conf

# Create SSL directory
sudo mkdir -p /etc/nginx/ssl

# Generate self-signed certificate
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/key.pem \
  -out /etc/nginx/ssl/cert.pem

# Or use Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot certonly --standalone -d yourdomain.com
# Update paths in nginx.conf

# Enable Nginx
sudo systemctl enable nginx
sudo systemctl restart nginx
```

**Cost**: $2.50-10/month
**Uptime**: 99.9-99.95%

---

## Monitoring & Maintenance

### Health Checks
```bash
# API Health
curl https://yourdomain.com/api/health

# Frontend Health
curl https://yourdomain.com/health

# Redis Health
redis-cli ping
```

### View Logs
```bash
# Backend logs
sudo journalctl -u trading-dashboard-backend -f

# Frontend logs
sudo journalctl -u trading-dashboard-frontend -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Application logs
tail -f ~/.hermes/logs/dashboard.log
tail -f ~/.hermes/logs/signals.jsonl
```

### Restart Services
```bash
# Docker Compose
docker-compose restart backend
docker-compose restart frontend

# Systemd
sudo systemctl restart trading-dashboard-backend
sudo systemctl restart trading-dashboard-frontend
```

### Backup Data
```bash
# Backup logs
tar -czf trading-logs-backup.tar.gz ~/.hermes/logs/

# Backup Redis
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb ./backup-$(date +%Y%m%d).rdb
```

---

## Performance Tuning

### Redis Optimization
```bash
# Increase max memory
redis-cli CONFIG SET maxmemory 256mb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Persist to disk
redis-cli CONFIG SET save "900 1 300 10 60 10000"
```

### Nginx Optimization
```bash
# In nginx.conf
worker_processes auto;
worker_connections 2048;
keepalive_timeout 65;

# Enable gzip
gzip on;
gzip_comp_level 6;
gzip_types text/plain text/css application/json application/javascript;
```

### Python Optimization
```bash
# Use uvicorn workers
# In systemd service: --workers 4 --worker-class uvicorn.workers.UvicornWorker
```

---

## Troubleshooting

### Port Already in Use
```bash
# Find process using port
lsof -i :8000

# Kill process
kill -9 <PID>
```

### API Returning 502 Bad Gateway
```bash
# Check if backend is running
sudo systemctl status trading-dashboard-backend

# Check logs
sudo journalctl -u trading-dashboard-backend -n 50
```

### WebSocket Connection Refused
```bash
# Check Nginx is forwarding WebSocket headers
# Look for: Upgrade, Connection headers in nginx.conf

# Test WebSocket
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  https://yourdomain.com/ws/prices
```

### High Memory Usage
```bash
# Check Redis memory
redis-cli INFO memory

# Check Python process
ps aux | grep python

# Reduce cache TTL in config.py
CACHE_TTL = 60  # Instead of 300
```

---

## SSL/TLS Setup (Let's Encrypt)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot certonly --standalone -d yourdomain.com

# Auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Verify renewal
sudo certbot renew --dry-run

# Update nginx.conf with certificate paths
ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
```

---

## Horizontal Scaling (Advanced)

### Load Balancing Multiple Backend Instances
```bash
# In docker-compose.yml
backend:
  deploy:
    replicas: 3
  
# Nginx upstream
upstream backend {
  server backend:8000;
  server backend:8001;
  server backend:8002;
}
```

### Shared Redis
```bash
# Use Redis cluster or managed Redis service
# Update REDIS_URL in .env
REDIS_URL=redis://managed-redis-service:6379/0
```

---

## Cost Estimate by Platform

| Platform | Monthly | Setup | Uptime |
|----------|---------|-------|--------|
| DigitalOcean | $12 | 5 min | 99.99% |
| AWS (free tier) | ~$0-5 | 15 min | 99.99% |
| AWS (t2.medium) | $35 | 15 min | 99.99% |
| Linode | $5 | 10 min | 99.9% |
| Hetzner | $3-5 | 10 min | 99.9% |
| Heroku | Deprecated | — | — |

---

## Next Steps

1. Choose deployment platform
2. Get Finnhub API key (free: https://finnhub.io)
3. Follow platform-specific instructions above
4. Monitor health via dashboard
5. Setup automated backups
6. Configure alerts for downtime
