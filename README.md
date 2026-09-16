# Portal Check Alerts

Checks whether the **Staging** and **Dev** portals are reachable every 10 minutes via GitHub Actions. Sends an **alert email** on first failure and a **recovery email** when the portal comes back up. State is persisted in a private GitHub Gist so duplicate emails are never sent.

| Portal | URL |
|---|---|
| Staging Portal | https://stgclient.vetty.co/client/login |
| Dev Portal | https://devapplicant.vetty.co/ |

Emails: **from** `hellolucifer007@gmail.com` → **to** `rishabh.gupta@vetty.co`

---

## How it works

```
Every 10 min
     │
     ▼
GitHub Actions runner spins up
     │
     ├─ Reads portal_state.json from private Gist   ← "was anything down last run?"
     │
     ├─ HTTP GET → Staging Portal
     ├─ HTTP GET → Dev Portal
     │
     ├─ Portal DOWN + was UP  →  send 🚨 DOWN alert email  →  write "down" to Gist
     ├─ Portal DOWN + was DOWN →  skip (already alerted)   →  no change to Gist
     ├─ Portal UP  + was DOWN  →  send ✅ RECOVERY email   →  write "up" to Gist
     └─ Portal UP  + was UP    →  nothing to do
```

State lives in a **secret GitHub Gist** — a private, permanent JSON file on GitHub's servers. No database, no cache expiry, no extra infrastructure.

---

## Requirements

- Python 3.11+
- `requests`, `python-dotenv`

```bash
pip install requests python-dotenv
```

---

## One-time setup (do this once, in order)

### Step 1 — Create a Gmail App Password

Normal Gmail passwords don't work with SMTP. You need an App Password.

1. Sign into `hellolucifer007@gmail.com`
2. Go to **Google Account → Security → 2-Step Verification** (enable it if not already)
3. Go to **App passwords** → create one, name it anything (e.g. "Portal Monitor")
4. Copy the 16-character password — you'll need it in Step 3

---

### Step 2 — Create a secret GitHub Gist

A Gist is a lightweight file store on GitHub. This one holds the portal state JSON.

1. Go to **https://gist.github.com** (log into your GitHub account)
2. Click **+** (top right) to create a new Gist
3. Fill in:
   - **Gist description:** `portal-check-state` (anything works)
   - **Filename:** `portal_state.json`
   - **Content:** `{}`
4. Set visibility to **Secret** (not Public) using the dropdown next to "Create Gist"
5. Click **Create secret gist**
6. Look at the URL: `https://gist.github.com/<your-username>/<GIST_ID>`
   Copy that last long hex string — that's your `GIST_ID`

---

### Step 3 — Create a GitHub Personal Access Token (PAT)

This lets the script read and write your Gist.

1. Go to **https://github.com/settings/tokens?type=beta** → **Generate new token**
2. Set a name: `portal-check-gist`
3. Set expiration: **No expiration** (or whatever your policy allows)
4. Under **Account permissions** → find **Gists** → set to **Read and write**
5. Leave **Repository access** as **None** — the token only needs Gist access
6. Click **Generate token** and copy it immediately (shown only once)

---

### Step 4 — Add secrets to the GitHub repo

The workflow reads these three values from GitHub Secrets — they are never stored in code.

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Add these three secrets one by one using **New repository secret**:

| Secret name | Value |
|---|---|
| `GMAIL_APP_PASSWORD` | The 16-char Gmail App Password from Step 1 |
| `GIST_TOKEN` | The PAT from Step 3 |
| `GIST_ID` | The hex ID from the Gist URL in Step 2 |

---

### Step 5 — Push and test

```bash
git add .
git commit -m "add portal health check"
git push
```

Then go to **Actions → Portal Health Check → Run workflow** to trigger a manual run and verify everything works before the first scheduled run.

---

## Schedule

| Repo visibility | Cron | Runs/month | Minutes used | Free limit |
|---|---|---|---|---|
| **Public** | `*/10 * * * *` | 4,320 | unlimited | ✅ free |
| **Private** | `*/30 * * * *` | 1,440 | ~1,440 min | ✅ under 2,000 |

To switch to 30-minute intervals, open `.github/workflows/portal-check.yml` and swap the commented lines.

---

## Email format

**DOWN alert** — subject: `🚨 ALERT: Staging Portal is DOWN`

**RECOVERY** — subject: `✅ RECOVERY: Staging Portal is back UP`

Both include the portal name, URL, failure reason (or downtime start time), and a UTC timestamp.

---

## Local usage

```bash
cp .env.example .env
# fill in .env with your credentials
python check_portals.py
```

---

## File overview

| File | Purpose |
|---|---|
| `check_portals.py` | Main script |
| `.env.example` | Credentials template |
| `.env` | Your actual credentials (never commit this) |
| `.github/workflows/portal-check.yml` | GitHub Actions scheduled workflow |
