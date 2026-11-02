#!/usr/bin/env bash
# Bright Coda Local Business Scout - one-time VPS installer (Ubuntu 22.04/24.04).
# Run from the project folder:  sudo bash deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null
fi

if [ ! -f .env ]; then
  read -rp "Domain for the app (e.g. scout.brightcoda.com): " DOMAIN
  read -rp "Admin login email [leon.tex610@gmail.com]: " ADMIN_EMAIL; ADMIN_EMAIL=${ADMIN_EMAIL:-leon.tex610@gmail.com}
  read -rsp "Admin password (min 10 chars): " ADMIN_PASSWORD; echo
  read -rsp "AI key (EMERGENT_LLM_KEY): " LLM; echo
  ENC=$(docker run --rm python:3.11-slim sh -c "pip -q install cryptography >/dev/null 2>&1 && python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'")
  JWT=$(openssl rand -hex 32)
  MPW=$(openssl rand -hex 20)
  cat > .env <<EOF
APP_DOMAIN=${DOMAIN}
PUBLIC_APP_URL=https://${DOMAIN}
CORS_ORIGINS=https://${DOMAIN}
MONGO_ROOT_USER=scout
MONGO_ROOT_PASSWORD=${MPW}
DB_NAME=brightcoda_scout
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
APP_ENCRYPTION_KEY=${ENC}
JWT_SECRET=${JWT}
EMERGENT_LLM_KEY=${LLM}
BACKUP_KEEP_DAYS=14
EOF
  chmod 600 .env
  echo ".env created. Keep a private copy of it - APP_ENCRYPTION_KEY is needed to read saved credentials."
fi

mkdir -p backups migrate
docker compose up -d --build
echo
echo "Waiting for services..."
sleep 20
docker compose ps
echo
echo "Done. Open https://$(grep ^APP_DOMAIN .env | cut -d= -f2) (HTTPS certificate is issued automatically once DNS points here)."
