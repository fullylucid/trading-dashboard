# GitHub + DigitalOcean Setup Guide

## Step 1: Create GitHub Repository

### Option A: GitHub Web UI (Easiest)
1. Go to https://github.com/new
2. **Repository name**: `trading-dashboard`
3. **Description**: `Real-time quantitative trading dashboard with Finnhub integration`
4. **Visibility**: Public (DigitalOcean needs public access) or Private with deploy key
5. **Create repository**

### Option B: GitHub CLI
```bash
gh repo create trading-dashboard --public --source=. --remote=origin --push
```

---

## Step 2: Push Code to GitHub

```bash
cd ~/.hermes/workspace/trading-dashboard

# Initialize git if not already done
git init
git config user.name "Your Name"
git config user.email "your-email@example.com"

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: production trading dashboard with FastAPI + React"

# Add remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/trading-dashboard.git

# Push to GitHub
git branch -M main
git push -u origin main
```

**Verify**: Visit https://github.com/YOUR_USERNAME/trading-dashboard — should show all files.

---

## Step 3: Get Finnhub API Key

1. Go to https://finnhub.io
2. Sign up (free tier: 60 req/min)
3. Dashboard → API Keys
4. Copy your key (e.g., `d7276q1r01qjeeeg64c...`)

---

## Step 4: Create DigitalOcean App

### Step 4a: Connect GitHub to DigitalOcean

1. Go to https://cloud.digitalocean.com/apps
2. Click **"Create App"**
3. Select **"GitHub"**
4. Click **"Authorize GitHub"** (if not already done)
5. Select your GitHub account
6. Search for `trading-dashboard` repo
7. Click to select it
8. Click **"Next"**

### Step 4b: Configure Services

You'll see "Configure Services" screen. Click the pencil icon next to **Backend** and **Frontend**.

#### Backend Configuration:
```
Name: backend
Source: /backend (directory)
Build Command: pip install -r requirements.txt
Run Command: python main.py
HTTP Port: 8000
```

#### Frontend Configuration:
```
Name: frontend
Source: /frontend (directory)
Build Command: npm install && npm run build
Run Command: npx serve -s build -l 5000
HTTP Port: 5000
```

### Step 4c: Add Environment Variables

Click **"Environment"** tab on the left.

Add these variables:
```
FINNHUB_API_KEY=<your-api-key-from-step-3>
REDIS_URL=<will-be-auto-populated>
TRADING_WATCHLIST_PATH=/tmp/watchlist.json
LOG_LEVEL=INFO
```

### Step 4d: Add Redis Database

1. Click **"Add Resource"** → **"Database"**
2. Select **"Redis"** from Marketplace
3. Keep defaults
4. Click **"Create"**

DigitalOcean will auto-populate `REDIS_URL` environment variable.

### Step 4e: Configure Domains (Optional)

1. Click **"Domains"** tab
2. Add your custom domain or use DigitalOcean subdomain
3. Recommended: `trading-yourname.ondigitalocean.app`

### Step 4f: Deploy!

Click **"Create App"** button at bottom-right.

**⏱️ Deployment takes 3-5 minutes**

Monitor progress in the "Deployments" tab.

---

## Step 5: Verify Deployment

Once deployment completes:

1. **Frontend**: Visit the app URL (e.g., `https://trading-yourname.ondigitalocean.app`)
   - Should show live watchlist ticker
   - Real-time price updates
   - 7-strategy quant scoreboard

2. **API Docs**: Visit `https://trading-yourname.ondigitalocean.app/docs`
   - Should show all API endpoints
   - Test endpoints with "Try it out" button

3. **Check Logs**: In DigitalOcean dashboard → App → Deployment → Logs
   - Backend logs show "Uvicorn running..."
   - Frontend logs show "Compiled successfully"

---

## Step 6: Verify Finnhub Integration

1. Go to dashboard
2. Watch watchlist ticker update in real-time (should see live prices)
3. If no prices show:
   - Check backend logs: Look for `[Finnhub]` messages
   - Verify `FINNHUB_API_KEY` is set correctly
   - Check Finnhub rate limits: https://finnhub.io/dashboard (should show API calls)

---

## Step 7: Connect Telegram Alerts (Optional)

To receive trading alerts on Telegram:

1. Get Telegram bot token:
   - Open Telegram
   - Search for `@BotFather`
   - `/newbot` → name your bot → copy token

2. Update environment variables in DigitalOcean:
   - Go to App → Settings → Environment
   - Add: `TELEGRAM_BOT_TOKEN=<your-bot-token>`
   - Add: `TELEGRAM_CHAT_ID=<your-chat-id>`
   - Redeploy

3. Get your Telegram chat ID:
   - Search for `@userinfobot` in Telegram
   - Send `/start`
   - Copy the `id:` number

---

## Troubleshooting

### App Won't Deploy
**Symptom**: Deployment stuck or failed
**Fix**: 
1. Check "Deployment" tab → "Logs"
2. Look for error messages
3. Common: Missing environment variable → add `FINNHUB_API_KEY`

### Prices Not Updating
**Symptom**: Frontend shows "Loading..." for watchlist
**Fix**:
1. Check backend logs for `[Finnhub]` errors
2. Verify Finnhub API key is correct (http://localhost:8000/api/health)
3. Check Finnhub rate limits

### Slow Loading
**Symptom**: Dashboard takes >3 sec to load
**Fix**:
1. Check network speed (DigitalOcean region affects latency)
2. Enable browser cache (frontend should cache prices)
3. Restart app: App → Deployment → Restart

---

## Cost Breakdown

| Component | Cost/month |
|-----------|-----------|
| 2x App Platform (frontend + backend) | $12 |
| Redis Database (256MB) | $3 |
| Bandwidth (included) | Free |
| **Total** | **~$15** |

---

## Next Steps

1. ✅ Create GitHub repo
2. ✅ Push code to GitHub
3. ✅ Create DigitalOcean app
4. ✅ Add Finnhub API key
5. ✅ Deploy
6. ⏳ Monitor dashboard for 24 hours
7. 📈 Start live trading (when confident)

---

## Quick Links

- GitHub: https://github.com/YOUR_USERNAME/trading-dashboard
- DigitalOcean: https://cloud.digitalocean.com/apps
- Finnhub: https://finnhub.io/dashboard
- Your App: `https://trading-yourname.ondigitalocean.app`

---

_Dashboard is now production-ready and autoscaling. Happy trading!_
