"""Diagnóstico: o que o Google Flights devolve além da lista de "melhores voos".

Uso (na VPS): python vps/diagnostico_cias.py
"""
import json
import time

from fast_flights import FlightQuery, Passengers, create_query
from fast_flights.fetcher import fetch_flights_html
from selectolax.lexbor import LexborHTMLParser

COMBOS = [("2027-04-28", "2027-05-20"), ("2027-04-29", "2027-05-23"), ("2027-04-30", "2027-05-25")]


def payload_de(ida, volta):
    q = create_query(
        flights=[FlightQuery(date=ida, from_airport="GRU", to_airport="LIS"),
                 FlightQuery(date=volta, from_airport="LIS", to_airport="GRU")],
        seat="economy", trip="round-trip", passengers=Passengers(adults=1),
        language="pt-BR", currency="BRL")
    html = fetch_flights_html(q)
    js = LexborHTMLParser(html).css_first(r"script.ds\:1").text()
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        return None
    return json.loads(data)


def resumo_lista(lista):
    saida = []
    for k in lista or []:
        try:
            voo, preco = k[0], k[1][0][1]
            escalas = "/".join(s[6] for s in voo[2])
            saida.append((preco, ", ".join(voo[1]), escalas))
        except Exception:
            continue
    return sorted(saida, key=lambda x: (x[0] is None, x[0] or 0))


for ida, volta in COMBOS:
    for tentativa in range(3):
        try:
            p = payload_de(ida, volta)
            break
        except Exception as e:
            p = None
            time.sleep(10)
    if not p:
        print(ida, volta, "sem resposta do Google")
        continue
    cias = [nome for _, nome in p[7][1][1]]
    print(f"\n{ida} -> {volta}")
    print("  companhias no filtro do Google:", ", ".join(cias))
    for idx in (2, 3):
        bloco = p[idx][0] if isinstance(p[idx], list) and p[idx] else None
        itens = resumo_lista(bloco)
        print(f"  lista payload[{idx}]: {len(itens)} opções")
        for preco, cia, escalas in itens[:6]:
            print(f"    R$ {preco} | {cia} | {escalas}")
        taag = [x for x in itens if "TAAG" in x[1].upper() or "ANGOLA" in x[1].upper()]
        if taag:
            print("    TAAG:", taag[:3])
    time.sleep(8)
