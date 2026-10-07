# ⚡ DocuChat AI — Master Run, Stop & Kill Commands Guide
### Complete Reference for Docker, Backend (FastAPI), Frontend (React / npm), and Ollama

---

## 📌 1. Quick Reference Cheat Sheet

| Service | 🚀 RUN Command | ⏹️ STOP Command (Graceful) | 💀 KILL Command (Force Kill) |
| :--- | :--- | :--- | :--- |
| **All Docker Containers** | `docker compose up -d` | `docker compose stop` or `docker compose down` | `docker kill $(docker ps -q)` |
| **Backend (FastAPI)** | `python main.py` | `Ctrl + C` in terminal | PowerShell: Kill Port `5000` *(see below)* |
| **Frontend (React)** | `npm start` | `Ctrl + C` then `y` | PowerShell: Kill Port `3000` *(see below)* |
| **Ollama (LLM Engine)** | `docker compose up -d ollama`<br>or `ollama serve` | `docker stop docuchat_ollama`<br>or `Ctrl + C` | PowerShell: Kill Port `11434` *(see below)* |
| **Qdrant (Vector DB)** | `docker compose up -d qdrant` | `docker stop docuchat_qdrant` | `docker kill docuchat_qdrant` |
| **Docling (Parser)** | `docker compose up -d docling` | `docker stop docuchat_docling` | `docker kill docuchat_docling` |

---

## 💥 Emergency 1-Line Kill Commands (When Ports are Stuck)

### 👉 Option A: Windows PowerShell (Recommended)
Copy and paste this into PowerShell to instantly kill whatever is blocking your ports:

```powershell
# Kill Backend (Port 5000)
Get-Process -Id (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Kill Frontend (Port 3000)
Get-Process -Id (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Kill Ollama (Port 11434)
Get-Process -Id (Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Kill Qdrant (Port 6333)
Get-Process -Id (Get-NetTCPConnection -LocalPort 6333 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Kill ALL Node.js and Python processes at once (Total Reset)
Stop-Process -Name "node", "python" -Force -ErrorAction SilentlyContinue
```

### 👉 Option B: Windows Command Prompt (CMD)
```cmd
:: Find PID on port 5000 and kill it
for /f "tokens=5" %a in ('netstat -aon ^| findstr :5000') do taskkill /f /pid %a

:: Find PID on port 3000 and kill it
for /f "tokens=5" %a in ('netstat -aon ^| findstr :3000') do taskkill /f /pid %a

:: Kill all python and node processes directly
taskkill /F /IM python.exe /T
taskkill /F /IM node.exe /T
```

---

## 🐳 2. Docker Commands

Run these inside `d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\`:

### 🚀 RUN / START Docker
```bash
# 1. Start all containers in background (-d)
docker compose up -d

# 2. Start ONLY infrastructure containers (Qdrant, Docling, Ollama, Postgres, Redis)
docker compose up -d qdrant docling ollama postgres redis

# 3. Start a single specific container
docker compose up -d qdrant
docker compose up -d ollama
docker compose up -d docling
```

### ⏹️ STOP Docker (Graceful)
```bash
# 1. Stop all containers (keeps containers and data intact)
docker compose stop

# 2. Stop and remove all containers and networks (safe, data volumes preserved)
docker compose down

# 3. Stop a single specific container
docker compose stop docuchat_qdrant
docker compose stop docuchat_ollama
docker compose stop docuchat_docling
```

### 💀 KILL / RESTART Docker (Force)
```bash
# Force kill a specific container immediately
docker kill docuchat_qdrant
docker kill docuchat_ollama
docker kill docuchat_docling
docker kill docuchat_backend
docker kill docuchat_frontend

# Force kill ALL running Docker containers on your machine
docker kill $(docker ps -q)

# Restart all containers
docker compose restart
```

### 🔍 CHECK STATUS & LOGS
```bash
# View status of all running containers
docker compose ps
# or
docker ps

# View live logs of a container
docker logs -f docuchat_backend
docker logs -f docuchat_ollama
docker logs -f docuchat_docling
docker logs -f docuchat_qdrant
```

### 🧹 CLEANUP DOCKER (Free Disk Space)
```bash
# Remove stopped containers and unused networks
docker container prune -f

# Total clean (removes containers, networks, and unused volumes)
docker compose down -v
```

---

## 🐍 3. Backend (FastAPI) Commands

Location: `d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\backend\`

### 🚀 RUN Backend
```powershell
# Step 1: Open Terminal & navigate to backend
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\backend"

# Step 2: (Optional) Install dependencies if needed
pip install -r requirements.txt

# Step 3: Start backend server (starts on http://localhost:5000)
python main.py
```

*Or with Uvicorn CLI directly:*
```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 5000 --reload
```

### 🔍 CHECK HEALTH
Open browser or run in terminal:
```powershell
curl http://localhost:5000/health
```

### ⏹️ STOP Backend (Graceful)
- Click on the terminal where backend is running and press:
  ```text
  Ctrl + C
  ```

### 💀 KILL Backend (When Port 5000 is stuck / already in use)
```powershell
# PowerShell:
Get-Process -Id (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Or kill all Python processes:
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
```

---

## ⚛️ 4. Frontend (React / npm) Commands

Location: `d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\frontend\`

### 🚀 RUN Frontend
```powershell
# Step 1: Open Terminal & navigate to frontend
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\frontend"

# Step 2: (First time only) Install node packages
npm install

# Step 3: Start React development server (opens at http://localhost:3000)
npm start
```

### ⏹️ STOP Frontend (Graceful)
- Click on the terminal running `npm start` and press:
  ```text
  Ctrl + C
  ```
- When asked `Terminate batch job (Y/N)?`, type:
  ```text
  y
  ```
- Press `Enter`.

### 💀 KILL Frontend (When Port 3000 is stuck / already in use)
```powershell
# PowerShell:
Get-Process -Id (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force

# Or kill all Node processes:
Stop-Process -Name "node" -Force -ErrorAction SilentlyContinue
```

---

## 🦙 5. Ollama (LLM Service) Commands

Ollama hosts the local LLM model (`qwen2.5:1.5b`) on port `11434`.

### 🚀 RUN Ollama
* **If using Docker (Standard):**
  ```bash
  docker compose up -d ollama
  ```
* **If using local Ollama app installed on Windows:**
  ```bash
  ollama serve
  ```

### 📥 PULL THE MODEL (One-Time Setup)
```bash
# If Ollama is inside Docker:
docker exec -it docuchat_ollama ollama pull qwen2.5:1.5b

# If Ollama is installed directly on Windows:
ollama pull qwen2.5:1.5b
```

### 🔍 CHECK OLLAMA MODELS
```bash
# Inside Docker:
docker exec -it docuchat_ollama ollama list

# Local Windows:
ollama list
```

### 💀 KILL Ollama (Port 11434)
```powershell
# Stop container:
docker stop docuchat_ollama

# Force kill port 11434 on Windows:
Get-Process -Id (Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

## 🔄 6. How to Run the Entire Project (Step-by-Step)

To run the complete system with 3 clean terminals:

### Terminal 1: Infrastructure (Docker)
```powershell
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main"
docker compose up -d
```

### Terminal 2: Backend (FastAPI)
```powershell
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\backend"
python main.py
```
*(Backend runs on `http://localhost:5000`)*

### Terminal 3: Frontend (React)
```powershell
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\frontend"
npm start
```
*(Frontend opens automatically at `http://localhost:3000`)*

---

## 🛑 7. How to Stop Everything Cleanly

When you want to stop working and shut down the computer:

1. **Stop Frontend:** In Terminal 3, press `Ctrl + C`, type `y`, hit `Enter`.
2. **Stop Backend:** In Terminal 2, press `Ctrl + C`.
3. **Stop Docker:** In Terminal 1, run:
   ```powershell
   docker compose down
   ```

---

## 🔧 8. Troubleshooting: Common Errors & 5-Second Fixes

### Error 1: `Port 5000 is already in use` or `Address already in use`
**Cause:** A previous python/uvicorn backend process was left running in the background.  
**Fix:** Run this in PowerShell:
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess | Stop-Process -Force
```

### Error 2: `Port 3000 is already in use`
**Cause:** A previous React `npm start` process is still holding port 3000.  
**Fix:** Run this in PowerShell:
```powershell
Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess | Stop-Process -Force
```

### Error 3: `Cannot connect to Qdrant at http://localhost:6333`
**Cause:** Qdrant Docker container is not started.  
**Fix:**
```powershell
docker compose up -d qdrant
```
*(Note: DocuChat also has an automatic fallback to local embedded disk storage `backend/data/qdrant_storage`).*

### Error 4: `Cannot connect to Ollama at http://localhost:11434`
**Cause:** Ollama service is not running or model is not pulled yet.  
**Fix:**
```powershell
docker compose up -d ollama
docker exec -it docuchat_ollama ollama pull qwen2.5:1.5b
```

### Error 5: `node_modules` or `npm start` fails
**Cause:** Dependencies missing or corrupted.  
**Fix:**
```powershell
cd "d:\AMD Files\Projects\Git rag\RAG-Based-ChatBot-Main\frontend"
npm install
npm start
```

---

*Keep this file saved for quick daily operations!*
