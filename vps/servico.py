"""Serviço do radar na VPS (separado do CRM).

Faz duas coisas:
  1. Roda a varredura do radar.py a cada 3 horas (0h, 3h, 6h ... 21h, horário de Brasília).
  2. Recebe avisos das rotinas do Claude em POST /enviar e repassa pelo WhatsApp.

O POST /enviar só aceita pedidos assinados com o RELAY_SECRET (HMAC-SHA256 do corpo, no
cabeçalho X-Assinatura), com horário de até 5 minutos e um código (nonce) nunca usado.
Ele só envia para os números do .env: "alerta" vai para WHATSAPP_DESTINO (Bianca) e
"interno" vai para o número conectado no WAHA (o seu). Ninguém consegue usar este endereço
para mandar mensagem a outra pessoa.
"""

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import traceback
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import radar  # noqa: E402

SEGREDO = os.environ["RELAY_SECRET"].encode()
WAHA = os.environ["WAHA_URL"].rstrip("/")
SESSAO = os.getenv("WAHA_SESSION") or "default"
CABECALHOS = {"X-Api-Key": os.environ["WAHA_API_KEY"]}
HORAS = [0, 3, 6, 9, 12, 15, 18, 21]
MINUTO = 7
LIMITE_HORA, LIMITE_DIA = 6, 20          # teto de mensagens recebidas pelo /enviar
JANELA_SEG = 300
trava = threading.Lock()
nonces = {}                               # nonce -> horário
envios = []                               # horários dos envios aceitos
chaves = {}                               # chave do aviso -> horário (evita repetir em 24h)


def log(msg):
    print(f"[{radar.agora():%d/%m %H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------ WhatsApp
def situacao():
    try:
        r = requests.get(f"{WAHA}/api/sessions/{SESSAO}", headers=CABECALHOS, timeout=15)
        return r.json() if r.ok else {"status": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"status": f"erro: {e}"}


def descobrir_meu_numero():
    """Preenche WHATSAPP_INTERNO com o número conectado, se não vier no .env."""
    while not os.getenv("WHATSAPP_INTERNO"):
        me = (situacao().get("me") or {}).get("id") or ""
        numero = me.split("@")[0].split(":")[0]
        if numero.isdigit():
            os.environ["WHATSAPP_INTERNO"] = numero
            log(f"Número conectado: {numero} (resumo diário e avisos internos vão para ele)")
            return
        time.sleep(60)


# ------------------------------------------------------------ varredura
def proxima(agora):
    for dia in range(2):
        base = (agora + timedelta(days=dia)).replace(second=0, microsecond=0)
        for h in HORAS:
            alvo = base.replace(hour=h, minute=MINUTO)
            if alvo > agora:
                return alvo
    return agora + timedelta(hours=3)


def loop_varredura():
    while True:
        alvo = proxima(radar.agora())
        log(f"Próxima varredura: {alvo:%d/%m %H:%M}")
        time.sleep(max(5, (alvo - radar.agora()).total_seconds()))
        if situacao().get("status") != "WORKING":
            log("WhatsApp não está conectado; a varredura roda e só grava o histórico.")
        try:
            radar.main()
        except Exception:
            traceback.print_exc()


# ------------------------------------------------------------ /enviar
def validar(corpo, assinatura):
    esperado = hmac.new(SEGREDO, corpo, hashlib.sha256).hexdigest()
    if not assinatura or not hmac.compare_digest(esperado, assinatura.strip().lower()):
        return None, 401, "assinatura inválida"
    try:
        d = json.loads(corpo)
    except Exception:
        return None, 400, "JSON inválido"
    agora = time.time()
    if not isinstance(d.get("ts"), (int, float)) or abs(agora - d["ts"]) > JANELA_SEG:
        return None, 401, "horário fora da janela"
    nonce = d.get("nonce")
    if not isinstance(nonce, str) or not 8 <= len(nonce) <= 64:
        return None, 400, "nonce inválido"
    if d.get("publico") not in ("alerta", "interno"):
        return None, 400, "publico deve ser alerta ou interno"
    texto = d.get("texto")
    if not isinstance(texto, str) or not 1 <= len(texto) <= 3500:
        return None, 400, "texto vazio ou longo demais"
    with trava:
        for n, t in list(nonces.items()):
            if agora - t > 2 * JANELA_SEG:
                del nonces[n]
        if nonce in nonces:
            return None, 401, "nonce repetido"
        nonces[nonce] = agora
        envios[:] = [t for t in envios if agora - t < 86400]
        if sum(1 for t in envios if agora - t < 3600) >= LIMITE_HORA or len(envios) >= LIMITE_DIA:
            return None, 429, "limite de mensagens atingido"
        chave = d.get("chave")
        if isinstance(chave, str) and chave:
            if agora - chaves.get(chave, 0) < 86400:
                return None, 200, "aviso repetido nas últimas 24h; não reenviado"
            chaves[chave] = agora
        envios.append(agora)
    return d, 200, "ok"


class Handler(BaseHTTPRequestHandler):
    def _resp(self, codigo, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/saude":
            return self._resp(200, {"ok": True, "whatsapp": situacao().get("status")})
        self._resp(404, {"erro": "não encontrado"})

    def do_POST(self):
        if self.path != "/enviar":
            return self._resp(404, {"erro": "não encontrado"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 12000:
            return self._resp(413, {"erro": "corpo inválido"})
        corpo = self.rfile.read(n)
        d, codigo, msg = validar(corpo, self.headers.get("X-Assinatura"))
        if d is None:
            log(f"/enviar recusado: {msg}")
            return self._resp(codigo, {"enviado": False, "motivo": msg})
        ok = radar.notificar("Radar SP-Lisboa", d["texto"], d["publico"])
        log(f"/enviar ({d['publico']}): {'enviado' if ok else 'falhou'}")
        self._resp(200 if ok else 502, {"enviado": ok})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=descobrir_meu_numero, daemon=True).start()
    threading.Thread(target=loop_varredura, daemon=True).start()
    log("Ponto de envio ouvindo na porta 8787")
    ThreadingHTTPServer(("0.0.0.0", 8787), Handler).serve_forever()
