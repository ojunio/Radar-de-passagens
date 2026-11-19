#!/usr/bin/env bash
# Instala o radar na VPS, em /opt/radar, separado do CRM. Uso (como root):
#   RELAY_SECRET=... WHATSAPP_DESTINO=55DDDNUMERO bash instalar.sh
set -euo pipefail
: "${RELAY_SECRET:?informe RELAY_SECRET}"
: "${WHATSAPP_DESTINO:?informe WHATSAPP_DESTINO}"

BASE=/opt/radar
mkdir -p "$BASE/data"
if [ -d "$BASE/app/.git" ]; then
  git -C "$BASE/app" pull -q
else
  git clone -q https://github.com/ojunio/Radar-de-passagens "$BASE/app"
fi
[ -f "$BASE/data/historico.csv" ] || cp "$BASE/app/data/historico.csv" "$BASE/data/"

if [ ! -f "$BASE/.env" ]; then
  umask 077
  cat > "$BASE/.env" <<EOF
WAHA_API_KEY=$(openssl rand -hex 24)
RELAY_SECRET=$RELAY_SECRET
WHATSAPP_DESTINO=$WHATSAPP_DESTINO
WHATSAPP_INTERNO=
EOF
fi

DC="docker compose -p radar -f $BASE/app/vps/docker-compose.yml --env-file $BASE/.env"
$DC up -d --build

if false; then  # porta 8787 só local; nada a liberar no firewall
  ufw allow 8787/tcp >/dev/null
fi

echo
echo "Radar no ar. Agora conecte o seu WhatsApp:"
$DC exec radar python vps/parear.py
