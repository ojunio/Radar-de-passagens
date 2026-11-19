"""Preço de uma companhia específica nas datas da viagem (filtro de companhia do Google Flights).

Uso (na VPS): python vps/checar_cia.py DT        (DT = TAAG Angola Airlines)
"""
import itertools
import random
import sys
import time

from fast_flights import FlightQuery, Passengers, create_query

sys.path.insert(0, "/app")
from voos import buscar_todos  # noqa: E402

CIA = (sys.argv[1] if len(sys.argv) > 1 else "DT").upper()
idas = ["2027-04-28", "2027-04-29", "2027-04-30"]
voltas = [f"2027-05-{d}" for d in range(20, 26)]
achados = []
for ida, volta in itertools.product(idas, voltas):
    q = create_query(
        flights=[FlightQuery(date=ida, from_airport="GRU", to_airport="LIS", airlines=[CIA]),
                 FlightQuery(date=volta, from_airport="LIS", to_airport="GRU", airlines=[CIA])],
        seat="economy", trip="round-trip", passengers=Passengers(adults=1),
        language="pt-BR", currency="BRL")
    try:
        voos = buscar_todos(q)
        if voos:
            b = min(voos, key=lambda v: v["preco"])
            achados.append((b["preco"], ida, volta, b["cias"], b["escalas"]))
            print(f"{ida} -> {volta}: R$ {b['preco']} | {b['cias']} | {b['escalas']}", flush=True)
        else:
            print(f"{ida} -> {volta}: nenhum voo dessa companhia", flush=True)
    except Exception as e:
        print(f"{ida} -> {volta}: erro {type(e).__name__}", flush=True)
    time.sleep(random.uniform(6, 10))

if achados:
    p, i, v, c, e = min(achados)
    print(f"\nMAIS BARATO {CIA}: R$ {p}/pessoa | GRU {i} -> {v} | {c} | {e}")
