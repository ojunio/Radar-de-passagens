#!/usr/bin/env bash
# Instala o WAHA (WhatsApp HTTP API) com HTTPS numa VPS Ubuntu ou Debian recém-criada.
# Uso, no terminal da VPS como root:
#   curl -fsSL https://raw.githubusercontent.com/ojunio/Radar-de-passagens/main/instalar-waha.sh | bash
# (ou copie este arquivo para a VPS e rode: bash instalar-waha.sh)
set -euo pipefail

IP=$(curl -fsS https://api.ipify.org)
HOST="$(echo "$IP" | tr . -).sslip.io"   # endereço gratuito que aponta para o IP da VPS
DIR=/opt/waha

if [ -f "$DIR/credenciais.txt" ]; then
  echo "WAHA já instalado. Credenciais em $DIR/credenciais.txt:"
  cat "$DIR/credenciais.txt"
  exit 0
fi

KEY=$(openssl rand -hex 24)
PASS=$(openssl rand -hex 12)

apt-get update -y
apt-get install -y ca-certificates curl openssl
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

mkdir -p "$DIR/sessions"
cd "$DIR"

cat > docker-compose.yml <<EOF
services:
  waha:
    image: devlikeapro/waha
    restart: unless-stopped
    environment:
      WAHA_API_KEY: "$KEY"
      WAHA_DASHBOARD_USERNAME: admin
      WAHA_DASHBOARD_PASSWORD: "$PASS"
      WHATSAPP_SWAGGER_USERNAME: admin
      WHATSAPP_SWAGGER_PASSWORD: "$PASS"
      WHATSAPP_DEFAULT_ENGINE: GOWS
    volumes:
      - ./sessions:/app/.sessions

  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    command: caddy reverse-proxy --from $HOST --to waha:3000
    volumes:
      - caddy_data:/data

volumes:
  caddy_data:
EOF

docker compose up -d

cat > credenciais.txt <<EOF
Endereço (WAHA_URL):     https://$HOST
Chave (WAHA_API_KEY):    $KEY
Painel:                  https://$HOST/dashboard
Usuário do painel:       admin
Senha do painel:         $PASS
EOF
chmod 600 credenciais.txt

echo
echo "================ WAHA instalado ================"
cat credenciais.txt
echo "================================================"
echo "Guarde esses dados. Eles ficam salvos em $DIR/credenciais.txt"
echo "O certificado HTTPS pode levar 1 ou 2 minutos para ficar pronto."
