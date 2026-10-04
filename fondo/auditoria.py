"""Auditoría: compara cada día lo que hace cada bot en vivo con lo que cabía esperar de él.

Para cada bot con unos días de rodaje vuelve a simular su estrategia sobre el histórico y mira dos cosas:

- Decaimiento. Coge todos los tramos de su histórico de la misma duración que lleva en vivo y mira
  cuántos fueron peores que su resultado real. Si casi ninguno lo fue (por debajo del percentil 5),
  el bot rinde peor de lo que explica la mala suerte: lo más probable es que su histórico fuera un
  espejismo. El comité lo despide sin esperar a que pierda más.
- Desvío. Si lo que ha hecho en vivo no se parece a lo que da la simulación en esas mismas fechas,
  algo falla en los datos o en la operativa. Solo avisa; no toca nada.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data, departamentos
from . import strategies as st
from .backtest import backtest, costes_de
from .paper import Mesa


def revisar(mesa: Mesa, cfg: dict, ahora: pd.Timestamp) -> dict:
    a, al, carpeta, exchange = cfg["auditoria"], mesa.al, cfg["rutas"]["datos"], cfg["exchange"]
    velas, comunes, cuenta = {}, {}, {"en_linea": 0, "decaimiento": 0, "desvio": 0}
    costes = departamentos.costes_con_medidas(al, cfg)        # con el mismo coste por moneda que cobra la mesa en vivo

    def cargar(simbolo: str, tf: str):
        if (simbolo, tf) not in velas:
            ruta = data.ruta_velas(carpeta, exchange, simbolo, tf)
            velas[(simbolo, tf)] = data.cargar_velas(carpeta, exchange, simbolo, tf) if ruta.exists() else None
        return velas[(simbolo, tf)]

    for e in al.estrategias(("incubadora", "aprobada")):
        c = al.cuenta(e["id"])
        if not c or c["ultima_vela"] is None:
            continue
        alta = pd.Timestamp(c["alta"])
        dias = (ahora - alta).total_seconds() / 86400.0
        df = cargar(e["simbolo"], e["tf"])
        if df is None:
            continue
        if e["nombre"] in st.TRANSVERSALES:
            universo = e["metricas"].get("universo") or [e["simbolo"]]
            clave = (e["nombre"], e["tf"], str(sorted(e["params"].items())), tuple(universo))
            if clave not in comunes:
                dfs = {s: d for s in universo if (d := cargar(s, e["tf"])) is not None}
                comunes[clave] = st.senal_transversal(e["nombre"], dfs, e["params"])
            sig = comunes[clave][e["simbolo"]]
        else:
            sig = st.senal(e["nombre"], df, e["params"])
        funding = data.funding_por_vela(df.index, e["tf"], data.cargar_funding(carpeta, exchange, e["simbolo"]), cfg["costes"]["funding_8h"])
        res = backtest(df, sig, e["tf"], costes_de(costes, e["simbolo"]), cfg["dimensionado"], funding)
        i0 = int(df.index.searchsorted(alta))
        n = len(df) - i0
        previas = res.trade_pnl[res.trade_inicio < i0]
        peor, seguidas = 0, 0
        for x in previas:                   # la racha de pérdidas más larga que ha tenido en su histórico
            seguidas = seguidas + 1 if x < 0 else 0
            peor = max(peor, seguidas)
        if len(previas) >= 20:
            al.set(f"racha:{e['id']}", peor)
        if dias < a["dias_min"] or c["trades"] < a["trades_min"] or n < 24 or i0 < 5 * n:   # poco rodaje, o poco histórico para comparar
            continue
        vivo, esperado = c["nav"] - 1.0, float(np.prod(1.0 + res.neto[i0:]) - 1.0)
        acum = np.concatenate([[0.0], np.cumsum(np.log1p(np.clip(res.neto[:i0], -0.99, None)))])
        tramos = acum[n:] - acum[:-n]                    # todos los tramos del histórico con la misma duración
        percentil = float((tramos <= np.log1p(max(vivo, -0.99))).mean())
        if percentil < a["percentil_min"]:
            estado = "decaimiento"
        elif abs(vivo - esperado) > a["desvio_max"] + 0.5 * abs(esperado):
            estado = "desvio"
        else:
            estado = "en_linea"
        cuenta[estado] += 1
        previo = al.get(f"auditoria:{e['id']}")
        al.set(f"auditoria:{e['id']}", {"estado": estado, "percentil": percentil, "vivo": vivo, "esperado": esperado, "ts": str(ahora)})
        if previo is None or previo["estado"] != estado:
            etiqueta = f"#{e['id']} {e['nombre']} {e['simbolo']} {e['tf']}"
            if estado == "decaimiento":
                al.evento(ahora, "Auditoría", "decaimiento", f"{etiqueta}: lleva {vivo:+.1%} en {dias:.0f} días en vivo; en su histórico solo el {percentil:.0%} "
                                                               "de los tramos igual de largos fueron peores. Rinde por debajo de lo que explica la mala suerte.")
            elif estado == "desvio":
                al.evento(ahora, "Auditoría", "desvio", f"{etiqueta}: en vivo lleva {vivo:+.1%} y la simulación de esas mismas fechas da {esperado:+.1%}. "
                                                          "No coinciden: hay que revisar datos u operativa.")
            elif previo is not None:
                al.evento(ahora, "Auditoría", "en_linea", f"{etiqueta}: vuelve a estar dentro de lo esperado.")
    total = sum(cuenta.values())
    if not total:
        al.evento(ahora, "Auditoría", "resumen", f"Hoy no hay nada que auditar: ningún bot lleva todavía {a['dias_min']} días de rodaje.")
    else:
        al.evento(ahora, "Auditoría", "resumen", f"Revisados {total} bots: {cuenta['en_linea']} dentro de lo esperado, "
                                                  f"{cuenta['decaimiento']} por debajo de lo que explica la suerte, {cuenta['desvio']} que no coinciden con su simulación.")
    al.commit()
    return cuenta
