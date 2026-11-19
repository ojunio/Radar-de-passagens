"""Leitura completa do Google Flights.

A biblioteca fast-flights só lê uma das duas listas que o Google devolve (payload[3]).
A outra (payload[2]) às vezes tem preços mais baratos, por isso este módulo lê as duas.
"""
import json

from fast_flights.exceptions import FlightsNotFound
from fast_flights.fetcher import fetch_flights_html
from selectolax.lexbor import LexborHTMLParser


def _ler_lista(lista):
    saida = []
    for k in lista or []:
        try:
            voo = k[0]
            preco = k[1][0][1]
            if not preco:
                continue
            trechos = voo[2]
            saida.append({
                "preco": float(preco),
                "cias": ", ".join(voo[1]),
                "paradas_ida": max(len(trechos) - 1, 0),
                "escalas": "/".join(t[6] for t in trechos),
            })
        except Exception:
            continue
    return saida


def buscar_todos(q):
    """Todas as opções de voo das duas listas, cada uma com preço por pessoa."""
    html = fetch_flights_html(q)
    script = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if script is None:
        raise FlightsNotFound("resposta sem dados de voos")
    data = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found; received error")
    p = json.loads(data)
    voos = []
    for idx in (2, 3):
        bloco = p[idx][0] if isinstance(p[idx], list) and p[idx] else None
        voos += _ler_lista(bloco)
    return voos
