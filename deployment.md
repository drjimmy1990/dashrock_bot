# Dashrock VPS Deployment Guide (Windows 11 RDP)

## Overview

Deploy the Dashrock trading engine on a Windows 11 RDP VPS to run 24/7. The setup involves:
- Python backend (engine + API)
- React frontend (Vite dashboard)
- PostgreSQL database (existing Supabase — no change needed)

---

## Step 1: Install Prerequisites

Open PowerShell **as Administrator** on the VPS and run:

```powershell
# 1. Install Python 3.11+
winget install Python.Python.3.12

# 2. Install Node.js 20+ (for dashboard)
winget install OpenJS.NodeJS.LTS

# 3. Install Git
winget install Git.Git
```

> [!IMPORTANT]
> After installing, **close and reopen** PowerShell so `python`, `node`, and `git` are in PATH.

Verify:
```powershell
python --version    # Should be 3.11+
node --version      # Should be 20+
git --version
```

---

## Step 2: Clone the Repository

```powershell
cd C:\Users\$env:USERNAME\Desktop
git clone <your-repo-url> dashrock-v2
cd dashrock-v2
```

**Or** just copy the entire `dashrock-v2` folder from your local machine via RDP drag-and-drop / OneDrive / USB.

---

## Step 3: Set Up Python Environment

```powershell
cd C:\Users\$env:USERNAME\Desktop\dashrock-v2

# Create virtual environment
python -m venv venv

# Activate it
.\venv\Scripts\Activate

# Install dependencies
pip install -e .
```

---

## Step 4: Configure Environment

Create/copy the `.env` file:

```powershell
# Copy from your local machine, or create manually:
notepad .env
```

**.env contents** (fill in your LIVE keys):
```env
# ─── Binance API ─────────────────────────────────────
BINANCE_API_KEY=<your-live-api-key>
BINANCE_API_SECRET=<your-live-api-secret>
BINANCE_TESTNET_API_KEY=70xpJyFswCgujJKamazYaDiqkgzofi7KgO3ilMvULJ0lc2JJhRUYD3NiTOpSJTYh
BINANCE_TESTNET_API_SECRET=W87lj9rlei7L7J5BpXbDh2p6bJmQSnrdOs5vigA1aMUDGOq5614rUMXKhspZQewD

# ─── Database (Supabase PostgreSQL — same as local) ──
DATABASE_URL=postgresql://postgres.owebggsixkbmtfiimjol:rXwjiVrwGo67XpZV@aws-0-eu-west-1.pooler.supabase.com:6543/postgres

# ─── Auth ────────────────────────────────────────────
JWT_SECRET=0I4hlFQ0jCrXmu7naZIBowXAVzq7htg39jlW1yXKSvDcTjGCW8b-48isEqM_kD7OoZjtgrhNfKWGVU_vIwweqA
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Dashrock@Pr0d!2026#Xr

# ─── Notifications (Optional) ───────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK=
```

---

## Step 5: Update config.yaml for Live Trading

```powershell
notepad config.yaml
```

Change **line 1**:
```yaml
mode: live      # was: testnet
```

> [!CAUTION]
> Only switch to `live` when you're ready. You can test with `testnet` first on the VPS to verify connectivity.

---

## Step 6: Build the Dashboard

```powershell
cd web
npm install
npm run build
cd ..
```

This creates `web/dist/` — the production-ready static files.

> [!NOTE]
> For **production**, you should serve the built dashboard via the engine's API (or a simple HTTP server), not `npm run dev`. But for initial testing, `npm run dev` works fine.

---

## Step 7: Run the Engine

### Option A: Quick Test (foreground)
```powershell
.\venv\Scripts\Activate
python -m dashrock run --port 8000
```

### Option B: Run as Background Service (Recommended for 24/7)

Create a startup script `start_dashrock.bat`:
```bat
@echo off
cd /d C:\Users\%USERNAME%\Desktop\dashrock-v2
call venv\Scripts\activate.bat
python -m dashrock run --port 8000
pause
```

**To auto-start on login** (survives RDP disconnects):
1. Press `Win + R` → type `shell:startup` → Enter
2. Copy `start_dashrock.bat` into that folder
3. The engine will auto-start when you log into the VPS

### Option C: Run as Windows Service (Most robust)

Install [NSSM](https://nssm.cc/download):
```powershell
# Download NSSM
Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile nssm.zip
Expand-Archive nssm.zip -DestinationPath C:\nssm

# Install Dashrock as a service
C:\nssm\nssm-2.24\win64\nssm.exe install DashrockEngine "C:\Users\%USERNAME%\Desktop\dashrock-v2\venv\Scripts\python.exe" "-m dashrock run --port 8000"

# Set working directory
C:\nssm\nssm-2.24\win64\nssm.exe set DashrockEngine AppDirectory "C:\Users\%USERNAME%\Desktop\dashrock-v2"

# Set to auto-start
C:\nssm\nssm-2.24\win64\nssm.exe set DashrockEngine Start SERVICE_AUTO_START

# Start it
C:\nssm\nssm-2.24\win64\nssm.exe start DashrockEngine
```

This runs even when nobody is logged in, auto-restarts on crash, and survives reboots.

---

## Step 8: Access the Dashboard Remotely

The dashboard runs on port 5173 (dev) or you can serve built files. To access from your local browser:

### Option 1: Direct Access (if VPS has public IP)
Open firewall ports:
```powershell
# Allow engine API
netsh advfirewall firewall add rule name="Dashrock API" dir=in action=allow protocol=tcp localport=8000

# Allow dashboard (if running npm run dev)
netsh advfirewall firewall add rule name="Dashrock Web" dir=in action=allow protocol=tcp localport=5173
```

Then access: `http://<VPS-IP>:5173`

### Option 2: Serve Dashboard from Engine (No separate web server)
The Vite build produces static files in `web/dist/`. You can configure the FastAPI engine to serve them. This way only port 8000 is needed.

---

## Step 9: Verify Connectivity

Run on the VPS:
```powershell
.\venv\Scripts\Activate
python test_ws.py
```

Expected output:
```
=== LIVE BINANCE FUTURES CONNECTIVITY TEST ===
1. REST API          — BTCUSDT ✅  XAGUSDT ✅
2. KLINE (/market)   — OK
3. BOOKTICKER        — OK
4. Combined stream   — ALL PASS
```

---

## Quick Checklist

| Step | Action | Status |
|------|--------|--------|
| 1 | Install Python + Node + Git | ☐ |
| 2 | Clone/copy project | ☐ |
| 3 | Create venv + `pip install -e .` | ☐ |
| 4 | Configure `.env` with live keys | ☐ |
| 5 | Set `mode: live` in config.yaml | ☐ |
| 6 | Build dashboard (`npm run build`) | ☐ |
| 7 | Start engine (choose A/B/C) | ☐ |
| 8 | Open firewall + access dashboard | ☐ |
| 9 | Run connectivity test | ☐ |

> [!TIP]
> **Recommended approach**: Option B (startup script) is the simplest. Option C (NSSM service) is best for production since it auto-restarts on crash and runs without an active login session.
