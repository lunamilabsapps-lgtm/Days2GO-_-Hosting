# Bright Coda Local Business Scout — Deployment & Operations Guide

## Architecture
| Service | Purpose |
|---|---|
| `proxy` (Caddy) | HTTPS (automatic Let's Encrypt), routes `/api/*` to the API and everything else to the frontend |
| `frontend` | React app (static, served by nginx) |
| `api` | FastAPI — REST + server-sent-event live stream (`RUN_WORKER=false`) |
| `worker` | Background agent: discovery, website assessment, scoring, email drafting, campaign sender, IMAP reply monitor, scheduled backups. Runs independently of any browser. |
| `mongo` | MongoDB 7 — persistent storage (volume `mongo_data`). Job queue and checkpoints live here, so restarts resume where they left off. |
| `backup` | Daily `mongodump` archives into `./backups` |

> The original brief suggested PostgreSQL + Redis. As agreed, this build uses MongoDB everywhere: job state, queues (atomic claim via `findOneAndUpdate`) and checkpoints are persisted in MongoDB, with unique indexes enforcing deduplication.

## 1. VPS preparation (Hostinger, Ubuntu 22.04/24.04)
```bash
ssh root@YOUR_VPS_IP
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
```
Point a DNS **A record** for your subdomain (e.g. `scout.brightcoda.com`) to the VPS IP.

## 2. Install
```bash
git clone <your-repo> /opt/scout && cd /opt/scout
cp .env.example .env
nano .env          # fill every value; generate APP_ENCRYPTION_KEY and JWT_SECRET
docker compose up -d --build
docker compose ps  # all services should become healthy
```
Open `https://<APP_DOMAIN>` and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## 3. Administrator setup (in the app)
1. **Settings → Sending → Sender**: sender name, sender email on your verified domain, reply-to (your Hostinger mailbox), ABN, business address, sign-off name.
2. **Service Catalogue**: review every service, add pricing/scope/terms. Only services marked *Approved for AI use* are pitched.
3. **Integrations → Resend**: paste your Resend API key (Sending access). Click **Test**.
4. **Integrations → Resend webhooks**: in Resend → Webhooks add the URL shown (`https://<APP_DOMAIN>/api/webhooks/resend`) with events delivered, bounced, complained, failed. Paste the signing secret.
5. **Integrations → IMAP**: host `imap.hostinger.com`, port 993, mailbox username/password, enable monitoring, **Test**.
6. **Settings → Compliance**: tick both confirmations once reviewed.
7. Keep **Test mode ON** until you've sent test campaigns to yourself. Switch it off to send to real prospects.

## 4. Required keys & configuration
| Item | Where |
|---|---|
| `EMERGENT_LLM_KEY` | `.env` — AI website analysis + email writing |
| `APP_ENCRYPTION_KEY`, `JWT_SECRET`, `ADMIN_*`, `MONGO_*` | `.env` |
| Resend API key + verified domain | Integrations screen (encrypted in DB) |
| Resend webhook signing secret | Integrations screen |
| Hostinger IMAP mailbox credentials | Integrations screen |
| OpenStreetMap (Nominatim/Overpass) | No key; public endpoints configurable in DB settings |

## 5. Updating
```bash
cd /opt/scout && git pull && docker compose up -d --build
```
Running searches resume automatically from their last completed suburb / business.

## 6. Backups & restore
- **Automatic**: the `backup` service writes `./backups/mongo-YYYYMMDD-HHMM.archive.gz` daily (kept `BACKUP_KEEP_DAYS`). The worker also writes JSON backups (Settings → Backups, downloadable).
- **Manual backup**:
  ```bash
  docker compose exec mongo sh -c 'mongodump -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db brightcoda_scout --gzip --archive' > scout-$(date +%F).archive.gz
  ```
- **Restore**:
  ```bash
  docker compose stop api worker
  cat scout-2026-01-01.archive.gz | docker compose exec -T mongo sh -c 'mongorestore -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --gzip --archive --drop'
  docker compose start api worker
  ```
- Copy `./backups` off the server regularly (e.g. `rclone` to cloud storage).
- Screenshots and JSON backups live in the `app_data` volume.

## 7. Database "migrations"
Indexes (uniqueness for businesses `source_key`, suppressions, coverage `(zone, category, source)`, outbound `message_id`, etc.) are created idempotently on every start by `core.create_indexes()`. Settings defaults are merged at read time, so new settings need no migration.

## 8. Health & logs
```bash
docker compose ps
docker compose logs -f worker
curl https://<APP_DOMAIN>/api/health
```
The top bar in the app shows *Worker offline* if the worker heartbeat stops.
