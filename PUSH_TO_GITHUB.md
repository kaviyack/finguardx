# How to Push FinGuardX to GitHub

Follow these steps exactly. Takes about 3 minutes.

---

## Step 1 — Create the GitHub repository

1. Go to **https://github.com/new**
2. Fill in:
   - **Repository name:** `finguardx`
   - **Description:** `Multi-Tenant SaaS Platform for Transaction Risk Assessment`
   - **Visibility:** Public or Private (your choice)
   - ❌ Do NOT check "Add a README file"
   - ❌ Do NOT add .gitignore or license (already included)
3. Click **"Create repository"**
4. Copy the repo URL shown — it will look like:
   `https://github.com/YOUR_USERNAME/finguardx.git`

---

## Step 2 — Extract the project on your machine

Download `finguardx_github_ready.zip` and extract it:

```bash
# Mac / Linux
unzip finguardx_github_ready.zip -d finguardx
cd finguardx

# Windows (PowerShell)
Expand-Archive finguardx_github_ready.zip -DestinationPath finguardx
cd finguardx
```

---

## Step 3 — Push to GitHub

```bash
# The repo already has git initialized with one commit
# Just add your GitHub remote and push

git remote add origin https://github.com/YOUR_USERNAME/finguardx.git

git push -u origin main
```

**If asked for credentials:**
- Username: your GitHub username
- Password: use a **Personal Access Token** (not your GitHub password)
  - Create one at: https://github.com/settings/tokens/new
  - Scopes needed: `repo` (full control)

---

## Step 4 — Verify on GitHub

Your repository should show:

```
finguardx/
├── .github/workflows/ci.yml     ← GitHub Actions CI
├── .env.example                  ← Environment config template
├── .gitignore
├── README.md
├── FinGuardX_API.postman_collection.json
├── backend/                      ← Flask Python API
│   ├── app.py
│   ├── test_finguardx.py
│   ├── risk_engine.py
│   ├── requirements.txt
│   └── Dockerfile
├── spring-backend/               ← Spring Boot Java
│   ├── pom.xml
│   └── src/...
├── risk-engine/                  ← ML scoring engine
│   ├── risk_engine.py
│   ├── dataset_loader.py
│   └── model/
├── frontend/                     ← HTML/CSS/JS SPA
│   ├── finguardx.html
│   ├── nginx.conf
│   └── Dockerfile
├── database/
│   └── schema.sql
└── docker/
    └── docker-compose.yml
```

---

## Step 5 — Enable GitHub Actions (optional but recommended)

1. Go to your repo → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**
3. Every push to `main` will now automatically:
   - Run all 72 Python tests
   - Verify model accuracy ≥ 85%
   - Run Spring Boot tests (mvn test)
   - Build Docker images

---

## Troubleshooting

**"src refspec main does not match any"**
```bash
git branch -M main
git push -u origin main
```

**"Repository not found" or 403**
- Check your Personal Access Token has `repo` scope
- Make sure the repo URL is exactly right

**Large file warning (>.joblib files)**
If GitHub rejects the trained model files (>100MB):
```bash
# Remove large model files from git tracking
echo "backend/model/*.joblib" >> .gitignore
echo "risk-engine/model/*.joblib" >> .gitignore
git rm --cached backend/model/*.joblib
git rm --cached risk-engine/model/*.joblib
git commit -m "chore: exclude large model files"
git push -u origin main
# Models will be regenerated on first run: python risk_engine.py train
```

---

## After pushing — run the project locally

```bash
# 1. Install Python deps
pip install flask PyJWT numpy pandas scikit-learn joblib

# 2. Train the model (first time only)
cd risk-engine && python risk_engine.py train && cd ..

# 3. Start the backend
cd backend && cp ../risk-engine/risk_engine.py . && cp -r ../risk-engine/model . && python app.py
# → Running on http://localhost:8080

# 4. Open frontend
# Open frontend/finguardx.html in your browser
# Login: analyst@axiombank.com / password123
```
