# 🚀 24/7 Free Cloud Hosting Guide for My Bet Bot

This guide walks you through deploying your Telegram Bet Bot online **100% free forever** so that it runs 24/7, performs automated morning sweeps at 10:30 AM Lagos time, checks bet results every 10 minutes, and provides instant predictions without your PC having to stay on.

---

## 🛠️ What We Already Prepared In Your Codebase

Your project is already 100% cloud-ready:
- **`render.yaml`**: Pre-configured Blueprint for 1-click deployment on Render.
- **`Dockerfile`**: Python 3.12-slim container with African timezone (`Africa/Lagos`) and healthcheck configured.
- **`Procfile`**: Process definition (`web: python main.py`) for cloud web runners.
- **`main.py` Cloud Server**: Built-in lightweight HTTP daemon responding `200 OK` on `/health` and `/` so free cloud hosts know the service is alive.
- **`.gitignore`**: Protects your secret API keys (`.env`) and local database (`ledger.db`) from being uploaded to public git.

---

## 🌟 Method 1: Render.com (Recommended — 100% Free)

Render provides **750 free hours every month** (a full month has 720–744 hours, so 1 web service runs completely free 24/7). 

Free Web Services on Render go to sleep after 15 minutes of web inactivity. **Because we built an HTTP `/health` server into your bot, we can use a free ping service (UptimeRobot) to keep it awake 24/7 permanently!**

### Step 1: Push Your Code to GitHub

1. Open your terminal in this project folder:
   ```powershell
   git add .
   git commit -m "feat: complete sportybet compound bot with 24/7 cloud readiness"
   ```
2. Go to [GitHub.com](https://github.com) and click **"New repository"**.
   - Name it: `my-bet-bot` (or any name you like).
   - Set it to **Private** (recommended) or Public.
   - Do NOT check "Initialize with README".
   - Click **Create repository**.
3. Link and push your local code (replace `YOUR_USERNAME` with your GitHub username):
   ```powershell
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/my-bet-bot.git
   git push -u origin main
   ```

---

### Step 2: Deploy on Render.com

1. Go to [Render.com](https://render.com) and **Sign Up / Log In** (you can sign in with your GitHub account).
2. Click the blue **"New +"** button at the top right, and select **"Blueprint"** (or "Web Service").
3. Connect your GitHub account and select your `my-bet-bot` repository.
4. Render will automatically read `render.yaml` and configure:
   - **Environment**: Python
   - **Region**: Frankfurt (closest to Nigeria / low latency)
   - **Plan**: Free
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Health Check Path**: `/health`
5. Under **Environment Variables**, fill in your secret keys (copied from your local `.env`):
   - `TELEGRAM_BOT_TOKEN`: (Your Telegram Bot Token from your local .env)
   - `TELEGRAM_ALLOWED_USER_ID`: (Your Telegram User ID from your local .env)
   - `AGENTROUTER_API_KEY`: (Your AgentRouter key from your local .env)
   - `ODDS_API_KEY`: (Your The Odds API key from your local .env)
6. Click **"Apply"** or **"Create Web Service"**.
7. Render will build and launch your bot within 1–2 minutes! You will see the build logs and then:
   ```text
   Cloud health-check server started on http://0.0.0.0:10000/health
   Bot is active and listening for messages.
   ```
8. Copy the URL Render gives your service (e.g. `https://my-bet-bot-xxxx.onrender.com`).

---

### Step 3: Keep It Awake 24/7 with UptimeRobot (Free)

Render free tier goes to sleep if no HTTP request arrives in 15 minutes. To prevent it from ever sleeping:

1. Go to [UptimeRobot.com](https://uptimerobot.com) and create a **Free Account**.
2. Click **"+ Add New Monitor"**.
3. Configure:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `My Bet Bot Ping`
   - **URL (or IP)**: `https://YOUR-APP-NAME.onrender.com/health`
   - **Monitoring Interval**: `10 minutes` (or 5 minutes)
4. Click **"Create Monitor"**.

Now UptimeRobot will ping your `/health` endpoint every 10 minutes. **Your bot will NEVER go to sleep and will run 24/7/365 completely free!**

---

## ⚡ Method 2: Koyeb.com (Alternative Free Forever — Never Sleeps)

Koyeb offers a free Eco tier (512MB RAM) that **does not spin down or sleep**, with zero pinging required:

1. Sign up on [Koyeb.com](https://koyeb.com) (sign in with GitHub).
2. Click **"Create Service"**.
3. Select **"GitHub"** as the deployment source and pick your `my-bet-bot` repository.
4. Builder: Koyeb will automatically detect `Dockerfile`.
5. Instance size: Choose **"Eco / Nano"** (Free).
6. Under **Environment Variables**, add the keys from your `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ALLOWED_USER_ID`
   - `AGENTROUTER_API_KEY`
   - `ODDS_API_KEY`
   - `TIMEZONE`: `Africa/Lagos`
   - `PORT`: `8080`
7. Click **"Deploy"**.

---

## ⚠️ CRITICAL NOTICE: Telegram Bot 1-Instance Rule

> [!WARNING]
> Telegram bots only allow **one instance** to receive updates at a time.
> If your bot is running on your laptop **AND** deployed to the cloud at the same time, Telegram will throw a `409 Conflict: terminated by other getUpdates request` error.

**Before activating your cloud bot:**
1. Stop your local bot running on your PC.
2. Once the cloud bot is live, it will take over permanently!

---

## 🧪 Testing Your Cloud Bot

Once deployed on Render or Koyeb:
1. Open your browser and visit:
   `https://YOUR-APP-NAME.onrender.com/health`
   You should see:
   ```json
   {"status": "online", "service": "telegram-bet-bot", "timezone": "Africa/Lagos", "briefing_time": "10:30", "port": 10000}
   ```
2. Open Telegram and send `/today` or `/status` to your bot.
3. Your bot will respond immediately from the cloud!
