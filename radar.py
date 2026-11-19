"""Radar de passagens: São Paulo -> Lisboa.

Varre todas as combinações de aeroporto de origem x data de ida x data de volta,
guarda o histórico e avisa (Telegram e/ou e-mail) quando aparece preço bom.

Fontes de preço:
  1. fast-flights (gratuita, lê o Google Flights). Fonte principal.
  2. SerpApi (opcional, 250 buscas grátis/mês). Usada para confirmar uma oferta
     antes do alerta e como reserva se a fonte 1 falhar.

Uso:
  python radar.py                  varredura normal
  python radar.py --teste          simula preços (sem internet) para testar a lógica
  python radar.py --teste-aviso    envia uma mensagem de teste nos canais configurados
"""

import csv
import html
import json
import os
import random
import smtplib
import sys
import time
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests

BRT = timezone(timedelta(hours=-3))  # Brasília, sem horário de verão
ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
MODO_TESTE = "--teste" in sys.argv
DATA = Path(os.getenv("RADAR_DATA_DIR") or ROOT / "data")  # na VPS: /data (fora do código)
if MODO_TESTE:
    DATA = ROOT / "data_teste"  # teste nunca suja o histórico real
HIST = DATA / "historico.csv"
STATE = DATA / "estado.json"
CAMPOS = ["varredura", "data_hora_brt", "origem", "ida", "volta",
          "preco_pessoa", "cias", "paradas_ida", "fonte"]


# ----------------------------------------------------------------- utilidades
def agora():
    return datetime.now(BRT)


def brl(v):
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def dias(inicio, fim):
    d, f = date.fromisoformat(inicio), date.fromisoformat(fim)
    out = []
    while d <= f:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def combinacoes():
    """Pares (ida, volta) da janela configurada."""
    return [(i, v) for i in dias(CFG["ida_inicio"], CFG["ida_fim"])
            for v in dias(CFG["volta_inicio"], CFG["volta_fim"])]


def fmt_data(iso):
    return date.fromisoformat(iso).strftime("%d/%m")


def link_google(origem, ida, volta):
    """Link do Google Flights já com o número de passageiros da viagem."""
    try:
        from fast_flights import FlightQuery, Passengers, create_query
        q = create_query(
            flights=[FlightQuery(date=ida, from_airport=origem, to_airport=CFG["destino"]),
                     FlightQuery(date=volta, from_airport=CFG["destino"], to_airport=origem)],
            seat="economy", trip="round-trip",
            passengers=Passengers(adults=CFG["passageiros"]),
            language="pt-BR", currency="BRL")
        return q.url()
    except Exception:
        return "https://www.google.com/travel/flights"


def carregar_estado():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def salvar_estado(st):
    DATA.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_historico():
    if not HIST.exists():
        return []
    with HIST.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["preco_pessoa"] = float(r["preco_pessoa"])
    return rows


def gravar_historico(linhas):
    DATA.mkdir(exist_ok=True)
    novo = not HIST.exists()
    with HIST.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerows(linhas)


# ------------------------------------------------------------- fonte 1: Google
def buscar_fast_flights(origem, ida, volta):
    """Menor preço ida e volta POR PESSOA (consulta feita com 1 adulto)."""
    from fast_flights import FlightQuery, Passengers, create_query, get_flights

    q = create_query(
        flights=[FlightQuery(date=ida, from_airport=origem, to_airport=CFG["destino"]),
                 FlightQuery(date=volta, from_airport=CFG["destino"], to_airport=origem)],
        seat="economy", trip="round-trip", passengers=Passengers(adults=1),
        language="pt-BR", currency="BRL")
    try:
        voos = get_flights(q)
    except Exception:
        # O Google às vezes responde "no flights found" por instabilidade; tenta mais uma vez.
        time.sleep(random.uniform(6, 12))
        voos = get_flights(q)
    res = [f for f in voos if f.price and f.price > 0]
    if not res:
        return None
    best = min(res, key=lambda f: f.price)
    return {"preco_pessoa": float(best.price),
            "cias": ", ".join(str(a) for a in best.airlines),
            "paradas_ida": max(len(best.flights) - 1, 0),
            "origem": origem}


# ------------------------------------------------------------ fonte 2: SerpApi
def serpapi_disponivel(st, n_buscas):
    if not os.getenv("SERPAPI_KEY"):
        return False
    mes = agora().strftime("%Y-%m")
    uso = st.setdefault("serpapi", {"mes": mes, "usadas": 0})
    if uso.get("mes") != mes:
        uso.update(mes=mes, usadas=0)
    return uso["usadas"] + n_buscas <= CFG["serpapi_limite_mensal"]


def buscar_serpapi(st, ida, volta):
    """Uma busca cobre todas as origens (a SerpApi aceita aeroportos separados por vírgula)."""
    params = {
        "engine": "google_flights",
        "departure_id": ",".join(CFG["origens"]),
        "arrival_id": CFG["destino"],
        "outbound_date": ida,
        "return_date": volta,
        "type": 1,            # ida e volta
        "travel_class": 1,    # econômica
        "adults": 1,          # preço por pessoa
        "currency": "BRL",
        "gl": "br",
        "api_key": os.environ["SERPAPI_KEY"],
    }
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=90)
    st["serpapi"]["usadas"] += 1
    r.raise_for_status()
    j = r.json()
    opcoes = [o for o in (j.get("best_flights") or []) + (j.get("other_flights") or [])
              if o.get("price")]
    insights = j.get("price_insights") or {}
    if not opcoes:
        return None
    best = min(opcoes, key=lambda o: o["price"])
    trechos = best.get("flights") or [{}]
    return {"preco_pessoa": float(best["price"]),
            "cias": ", ".join(dict.fromkeys(t.get("airline", "?") for t in trechos)),
            "paradas_ida": max(len(trechos) - 1, 0),
            "origem": (trechos[0].get("departure_airport") or {}).get("id", "SAO"),
            "nivel": insights.get("price_level"),
            "faixa_tipica": insights.get("typical_price_range"),
            "link": (j.get("search_metadata") or {}).get("google_flights_url")}


# ------------------------------------------------------------ modo de teste
def preco_simulado(origem, ida, volta):
    base = {"GRU": 4700, "VCP": 4500, "CGH": 5200}[origem]
    return {"preco_pessoa": float(base + random.randint(-900, 600)),
            "cias": random.choice(["TAP", "LATAM", "Azul", "Iberia, LATAM", "TAAG"]),
            "paradas_ida": random.choice([0, 1, 2]), "origem": origem}


# ------------------------------------------------------------ varredura
def varrer(st):
    vid = agora().strftime("%Y%m%d%H%M")
    stamp = agora().strftime("%Y-%m-%d %H:%M")
    tarefas = [(o, i, v) for o in CFG["origens"] for (i, v) in combinacoes()]
    random.shuffle(tarefas)
    linhas, erros = [], 0

    for n, (o, i, v) in enumerate(tarefas, 1):
        try:
            r = preco_simulado(o, i, v) if MODO_TESTE else buscar_fast_flights(o, i, v)
        except Exception as e:
            erros += 1
            print(f"[{n}/{len(tarefas)}] {o} {i}->{v}: erro {type(e).__name__}: {e}")
            r = None
        if r:
            linhas.append({"varredura": vid, "data_hora_brt": stamp, "origem": o,
                           "ida": i, "volta": v, "preco_pessoa": r["preco_pessoa"],
                           "cias": r["cias"], "paradas_ida": r["paradas_ida"],
                           "fonte": "teste" if MODO_TESTE else "google"})
            print(f"[{n}/{len(tarefas)}] {o} {i}->{v}: {brl(r['preco_pessoa'])} {r['cias']}")
        if not MODO_TESTE:
            time.sleep(random.uniform(CFG["pausa_min_seg"], CFG["pausa_max_seg"]))

    # Reserva: fonte principal não trouxe nada -> varredura completa pela SerpApi
    pares = combinacoes()
    ultima = st.get("serpapi_ultima_varredura")
    pode_por_tempo = (not ultima or agora() - datetime.fromisoformat(ultima)
                      >= timedelta(hours=CFG["serpapi_horas_entre_varreduras"]))
    if not linhas and not MODO_TESTE and pode_por_tempo and serpapi_disponivel(st, len(pares)):
        print("Fonte principal sem resultados. Usando SerpApi como reserva.")
        st["serpapi_ultima_varredura"] = agora().isoformat()
        for i, v in pares:
            try:
                r = buscar_serpapi(st, i, v)
            except Exception as e:
                print(f"SerpApi {i}->{v}: erro {e}")
                r = None
            if r:
                linhas.append({"varredura": vid, "data_hora_brt": stamp, "origem": r["origem"],
                               "ida": i, "volta": v, "preco_pessoa": r["preco_pessoa"],
                               "cias": r["cias"], "paradas_ida": r["paradas_ida"],
                               "fonte": "serpapi"})
    print(f"Varredura {vid}: {len(linhas)} preços, {erros} erros, {len(tarefas)} consultas.")
    return linhas


# ------------------------------------------------------------ regras de alerta
def minimos_por_varredura(hist):
    m = {}
    for r in hist:
        k = r["varredura"]
        if k not in m or r["preco_pessoa"] < m[k]["preco_pessoa"]:
            m[k] = r
    return sorted(m.values(), key=lambda r: r["varredura"])


def avaliar(linhas, hist_anterior):
    """Devolve (melhor oferta, lista de motivos). Motivos vazios = sem alerta."""
    if not linhas:
        return None, []
    melhor = min(linhas, key=lambda r: r["preco_pessoa"])
    p = melhor["preco_pessoa"]
    motivos = []

    if p <= CFG["teto_urgente_por_pessoa"]:
        motivos.append(f"PREÇO EXCEPCIONAL: abaixo de {brl(CFG['teto_urgente_por_pessoa'])} "
                       "por pessoa, vale decidir rápido")
    elif p <= CFG["teto_por_pessoa"]:
        motivos.append(f"abaixo do teto de {brl(CFG['teto_por_pessoa'])} por pessoa")

    anteriores = minimos_por_varredura(hist_anterior)
    if len(anteriores) >= CFG["varreduras_aquecimento"]:
        minimo_hist = min(r["preco_pessoa"] for r in anteriores)
        if p < minimo_hist - CFG["margem_novo_minimo"]:
            motivos.append(f"menor preço desde o início do radar (antes: {brl(minimo_hist)})")

        limite = (agora() - timedelta(days=7)).strftime("%Y%m%d%H%M")
        recentes = [r["preco_pessoa"] for r in anteriores if r["varredura"] >= limite]
        if recentes:
            media = sum(recentes) / len(recentes)
            queda = (media - p) / media * 100
            if queda >= CFG["queda_minima_pct"]:
                motivos.append(f"{queda:.0f}% abaixo da média dos últimos 7 dias ({brl(media)})")
    return melhor, motivos


def ja_avisado(st, melhor):
    """Evita repetir alerta: dentro da janela de silêncio, só avisa de novo se o
    preço cair pelo menos `margem_novo_minimo` abaixo do último preço avisado."""
    reg = st.get("ultimo_alerta")
    if not reg:
        return False
    recente = agora() - datetime.fromisoformat(reg["quando"]) < timedelta(
        hours=CFG["horas_sem_repetir_alerta"])
    return recente and melhor["preco_pessoa"] > reg["preco"] - CFG["margem_novo_minimo"]


def registrar_aviso(st, melhor):
    st["ultimo_alerta"] = {"quando": agora().isoformat(), "preco": melhor["preco_pessoa"],
                           "combinacao": f"{melhor['origem']} {melhor['ida']} {melhor['volta']}"}


# ------------------------------------------------------------ mensagens
def linha_oferta(r):
    paradas = "direto" if int(r["paradas_ida"]) == 0 else f"{r['paradas_ida']} parada(s) na ida"
    return (f"{r['origem']} {fmt_data(r['ida'])} → LIS, volta {fmt_data(r['volta'])}: "
            f"<b>{brl(r['preco_pessoa'])}</b>/pessoa · {html.escape(r['cias'])} · {paradas}")


def montar_alerta(melhor, motivos, linhas, confirmacao):
    n = CFG["passageiros"]
    p = melhor["preco_pessoa"]
    txt = [f"<b>Passagem SP → Lisboa: {brl(p)} por pessoa</b>",
           f"Estimativa para {n} pessoas: {brl(p * n)}", "",
           linha_oferta(melhor), "", "Por que avisei:"]
    txt += [f"• {m}" for m in motivos]
    if confirmacao:
        nivel = {"low": "baixo", "typical": "típico", "high": "alto"}.get(
            confirmacao.get("nivel") or "", "sem classificação")
        txt += ["", f"Conferido na SerpApi: {brl(confirmacao['preco_pessoa'])}/pessoa, "
                    f"o Google classifica como preço <b>{nivel}</b>."]
        faixa = confirmacao.get("faixa_tipica")
        if faixa and len(faixa) == 2:
            txt.append(f"Faixa típica da rota: {brl(faixa[0])} a {brl(faixa[1])}")
    outras = sorted(linhas, key=lambda r: r["preco_pessoa"])[1:4]
    if outras:
        txt += ["", "Outras boas combinações agora:"] + [f"• {linha_oferta(r)}" for r in outras]
    link = (confirmacao or {}).get("link") or link_google(melhor["origem"], melhor["ida"],
                                                            melhor["volta"])
    txt += ["", f'<a href="{html.escape(link)}">Abrir no Google Flights</a>',
            "Preço capturado agora; tarifa promocional pode sumir em horas. "
            "Confira no site antes de comprar (a tarifa mais barata pode não ter 2 assentos)."]
    return "\n".join(txt)


def montar_resumo(hist):
    ontem =(agora() - timedelta(days=1)).strftime("%Y%m%d%H%M")
    ult24 = [r for r in hist if r["varredura"] >= ontem]
    if not ult24:
        return None
    melhor_por_combo = {}
    for r in ult24:
        k = (r["origem"], r["ida"], r["volta"])
        if k not in melhor_por_combo or r["preco_pessoa"] < melhor_por_combo[k]["preco_pessoa"]:
            melhor_por_combo[k] = r
    top = sorted(melhor_por_combo.values(), key=lambda r: r["preco_pessoa"])[:5]
    minimo_total = min(r["preco_pessoa"] for r in hist)
    n = CFG["passageiros"]
    txt = [f"<b>Radar de passagens SP → Lisboa · {agora().strftime('%d/%m')}</b>",
           f"{n} adultos, econômica, ida de {fmt_data(CFG['ida_inicio'])} a {fmt_data(CFG['ida_fim'])}, "
           f"volta de {fmt_data(CFG['volta_inicio'])} a {fmt_data(CFG['volta_fim'])}. "
           "Preço por pessoa, ida e volta, sem bagagem despachada.", "",
           f"Melhor agora: <b>{brl(top[0]['preco_pessoa'])}</b>/pessoa "
           f"(cerca de {brl(top[0]['preco_pessoa'] * n)} para {n} pessoas)",
           f"Menor preço visto desde {fmt_data(min(r['data_hora_brt'] for r in hist)[:10])}: "
           f"{brl(minimo_total)}/pessoa", "",
           "Melhores combinações nas últimas 24h:"] + [f"• {linha_oferta(r)}" for r in top]
    link = link_google(top[0]["origem"], top[0]["ida"], top[0]["volta"])
    txt += ["", f'<a href="{html.escape(link)}">Abrir a melhor no Google Flights</a>']
    return "\n".join(txt)


# ------------------------------------------------------------ envio
def html_para_whatsapp(texto_html):
    """Converte o HTML simples das mensagens para a formatação do WhatsApp."""
    import re
    t = re.sub(r'<a href="([^"]+)">([^<]+)</a>', lambda m: f"{m.group(2)}: {m.group(1)}", texto_html)
    t = re.sub(r"</?b>", "*", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


def waha_chat_id(base, headers, sessao, numero):
    """Descobre o chatId correto (resolve o caso do 9º dígito de números brasileiros antigos)."""
    numero = "".join(c for c in numero if c.isdigit())
    try:
        r = requests.get(f"{base}/api/contacts/check-exists", headers=headers,
                         params={"phone": numero, "session": sessao}, timeout=30)
        r.raise_for_status()
        j = r.json()
        if j.get("numberExists") and j.get("chatId"):
            return j["chatId"]
        print(f"WhatsApp: o número {numero} não foi encontrado no WhatsApp.")
        return None
    except Exception as e:
        print(f"WhatsApp: falha ao verificar {numero} ({e}); tentando o formato padrão.")
        return f"{numero}@c.us"


def enviar_whatsapp(texto_html, publico):
    """publico='alerta' vai para WHATSAPP_DESTINO; publico='interno' vai para WHATSAPP_INTERNO."""
    base = (os.getenv("WAHA_URL") or "").rstrip("/")
    chave = os.getenv("WAHA_API_KEY")
    sessao = os.getenv("WAHA_SESSION") or "default"
    destinos = os.getenv("WHATSAPP_DESTINO" if publico == "alerta" else "WHATSAPP_INTERNO")
    if not (base and chave and destinos):
        return False
    headers = {"X-Api-Key": chave, "Content-Type": "application/json"}
    texto = html_para_whatsapp(texto_html)
    ok = False
    for numero in [n.strip() for n in destinos.split(",") if n.strip()]:
        chat = waha_chat_id(base, headers, sessao, numero)
        if not chat:
            continue
        try:
            r = requests.post(f"{base}/api/sendText", headers=headers, timeout=30,
                              json={"session": sessao, "chatId": chat, "text": texto,
                                    "linkPreview": False})
            r.raise_for_status()
            ok = True
        except Exception as e:
            print(f"WhatsApp falhou ({numero}): {e}")
        time.sleep(random.uniform(2, 4))
    return ok


def notificar(assunto, texto_html, publico="alerta"):
    """publico='alerta': ofertas (vai para a Bianca). publico='interno': resumo e falhas (só você)."""
    enviado = enviar_whatsapp(texto_html, publico)
    tok, chats = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chats:
        for chat in [c.strip() for c in chats.split(",") if c.strip()]:
            try:
                r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                                  json={"chat_id": chat, "text": texto_html,
                                        "parse_mode": "HTML"}, timeout=30)
                r.raise_for_status()
                enviado = True
            except Exception as e:
                print(f"Telegram falhou ({chat}): {e}")

    rem, senha, dest = (os.getenv("EMAIL_REMETENTE"), os.getenv("EMAIL_SENHA_APP"),
                        os.getenv("EMAIL_DESTINO"))
    if rem and senha and dest:
        try:
            msg = MIMEText(texto_html.replace("\n", "<br>"), "html", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = assunto, rem, dest
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
                s.login(rem, senha)
                s.sendmail(rem, [d.strip() for d in dest.split(",")], msg.as_string())
            enviado = True
        except Exception as e:
            print(f"E-mail falhou: {e}")

    if not enviado:
        print("Nenhum canal enviou. Mensagem:\n" + texto_html)
    return enviado


# ------------------------------------------------------------ principal
def main():
    if "--teste-aviso" in sys.argv:
        publico = "alerta" if "--para-bianca" in sys.argv else "interno"
        ok = notificar("Radar SP → Lisboa: teste",
                       "<b>Teste do radar SP → Lisboa</b>\nSe você recebeu isto, o canal está configurado.",
                       publico)
        sys.exit(0 if ok else 1)

    if "--exemplo-alerta" in sys.argv:
        # Manda um alerta de exemplo, com os preços da última varredura, para WHATSAPP_DESTINO.
        hist = carregar_historico()
        if not hist:
            print("Sem histórico para montar o exemplo.")
            sys.exit(1)
        ultima = max(r["varredura"] for r in hist)
        linhas = [r for r in hist if r["varredura"] == ultima]
        melhor = min(linhas, key=lambda r: r["preco_pessoa"])
        texto = ("<b>[TESTE do radar, pode ignorar]</b>\n"
                 f"Preços da varredura de {linhas[0]['data_hora_brt']}\n\n"
                 + montar_alerta(melhor, ["exemplo de alerta"], linhas, None))
        ok = notificar("Radar SP-Lisboa: teste", texto, "alerta")
        sys.exit(0 if ok else 1)

    if "--enviar" in sys.argv:
        # Usado pelas rotinas do Claude: envia o texto de um arquivo para os destinatários de alerta.
        arq = Path(sys.argv[sys.argv.index("--enviar") + 1])
        ok = notificar("Radar SP-Lisboa: promoção", arq.read_text(encoding="utf-8"), "alerta")
        sys.exit(0 if ok else 1)

    st = carregar_estado()
    hist_anterior = carregar_historico()
    linhas = varrer(st)

    if linhas:
        st["falhas_seguidas"] = 0
        gravar_historico(linhas)
        melhor, motivos = avaliar(linhas, hist_anterior)
        # A Bianca só recebe alerta de preço dentro do teto. Novo mínimo ou queda acima dele: só registro.
        dentro_do_teto = melhor["preco_pessoa"] <= CFG["teto_por_pessoa"]
        if motivos and dentro_do_teto and not ja_avisado(st, melhor):
            confirmacao = None
            if not MODO_TESTE and serpapi_disponivel(st, 1):
                try:
                    confirmacao = buscar_serpapi(st, melhor["ida"], melhor["volta"])
                except Exception as e:
                    print(f"Confirmação SerpApi falhou: {e}")
            notificar(f"Passagem SP-Lisboa: {brl(melhor['preco_pessoa'])} por pessoa",
                      montar_alerta(melhor, motivos, linhas, confirmacao), "alerta")
            registrar_aviso(st, melhor)
        elif motivos and not dentro_do_teto:
            print(f"Acima do teto, sem aviso: {brl(melhor['preco_pessoa'])} ({'; '.join(motivos)})")
        else:
            print("Sem alerta nesta varredura." if not motivos else "Oferta já avisada.")
    else:
        # Falha técnica não vai para o WhatsApp de ninguém: fica só no log da VPS.
        st["falhas_seguidas"] = st.get("falhas_seguidas", 0) + 1
        print(f"Varredura sem nenhum preço ({st['falhas_seguidas']} seguidas).")

    hoje = agora().date().isoformat()
    forcar = "--enviar-resumo" in sys.argv
    if forcar or (agora().hour >= CFG["resumo_diario_hora"] and st.get("ultimo_resumo") != hoje):
        resumo = montar_resumo(carregar_historico())
        if resumo:
            notificar("Radar SP-Lisboa: resumo do dia", resumo, "alerta")
            st["ultimo_resumo"] = hoje

    salvar_estado(st)


if __name__ == "__main__":
    main()
