"""Conecta o seu WhatsApp ao WAHA do radar: mostra o QR code no terminal até conectar."""

import os
import sys
import time

import qrcode
import requests

WAHA = os.environ["WAHA_URL"].rstrip("/")
SESSAO = os.getenv("WAHA_SESSION") or "default"
H = {"X-Api-Key": os.environ["WAHA_API_KEY"], "Accept": "application/json"}


def status():
    r = requests.get(f"{WAHA}/api/sessions/{SESSAO}", headers=H, timeout=15)
    return r.json() if r.ok else None


for _ in range(30):  # o WAHA pode levar alguns segundos para subir
    try:
        requests.get(f"{WAHA}/api/sessions", headers=H, timeout=5)
        break
    except Exception:
        time.sleep(2)

if status() is None:
    requests.post(f"{WAHA}/api/sessions", headers=H, timeout=30,
                  json={"name": SESSAO, "start": True}).raise_for_status()

ultimo, inicio = None, time.time()
while time.time() - inicio < 600:
    s = status() or {}
    st = s.get("status")
    if st == "WORKING":
        me = s.get("me") or {}
        print("\033[2J\033[H")
        print(f"CONECTADO: {me.get('id', '?')} ({me.get('pushName', '')})")
        sys.exit(0)
    if st == "STOPPED":
        requests.post(f"{WAHA}/api/sessions/{SESSAO}/start", headers=H, timeout=30)
    elif st == "FAILED":
        requests.post(f"{WAHA}/api/sessions/{SESSAO}/restart", headers=H, timeout=30)
    elif st == "SCAN_QR_CODE":
        r = requests.get(f"{WAHA}/api/{SESSAO}/auth/qr?format=raw", headers=H, timeout=15)
        valor = r.json().get("value") if r.ok else None
        if valor and valor != ultimo:
            ultimo = valor
            print("\033[2J\033[H")
            print("WhatsApp > Configurações > Aparelhos conectados > Conectar aparelho")
            q = qrcode.QRCode(border=2)
            q.add_data(valor)
            q.print_ascii(invert=True)
    else:
        print(f"Aguardando o WhatsApp ({st})...")
    time.sleep(3)

print("Tempo esgotado. Rode o comando de novo.")
sys.exit(1)
