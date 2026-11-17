import itertools, random, sys, time
from fast_flights import FlightQuery, Passengers, create_query, get_flights
idas = ['2027-04-28', '2027-04-29', '2027-04-30']
voltas = [f'2027-05-{d}' for d in range(20, 26)]
origens = ['GRU', 'VCP', 'CGH']
def q(o, i, v, n):
    return create_query(flights=[FlightQuery(date=i, from_airport=o, to_airport='LIS'),
                                 FlightQuery(date=v, from_airport='LIS', to_airport=o)],
                        seat='economy', trip='round-trip', passengers=Passengers(adults=n),
                        language='pt-BR', currency='BRL')
combos = list(itertools.product(origens, idas, voltas))[: int(sys.argv[1]) if len(sys.argv) > 1 else None]
res = []
for o, i, v in combos:
    for tentativa in range(2):
        try:
            fs = [f for f in get_flights(q(o, i, v, 1)) if f.price]
            if fs:
                b = min(fs, key=lambda f: f.price)
                res.append((b.price, o, i, v, ', '.join(b.airlines), len(b.flights) - 1))
            break
        except Exception:
            time.sleep(8)
    time.sleep(random.uniform(2, 5))
for p, o, i, v, c, s in sorted(res)[:5]:
    print(f'R$ {p}/pessoa | {o} {i} -> {v} | {c} | {s} parada(s) na ida | {q(o, i, v, 2).url()}')
print(f'consultas com preço: {len(res)} de {len(combos)}')
