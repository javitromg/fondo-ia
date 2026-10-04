"""Biblioteca: modelos publicados, con reglas fijas, que el fondo contrata tal cual.

La minería busca parámetros a ciegas y casi todo lo que encuentra es suerte. Aquí se hace lo contrario:
se cogen modelos cuyas reglas ya están publicadas y replicadas por otros, sin afinar nada, y se comprueba
qué habrían hecho con los datos de nuestro exchange. Como no hay nada que ajustar, no hay tramos de
entrenamiento ni validación: se mira todo el histórico de una vez y se compara con dos cosas.

- Referencia: comprar todas las monedas y mantenerlas, con el mismo control de tamaño. Un modelo que
  solo gana porque el mercado subió no aporta nada frente a esto.
- Ruido: el mismo modelo sobre versiones "placebo" del histórico (misma subida total, mismo tamaño de
  movimientos, sin patrón sobre cuándo ocurren). El p-valor dice en cuántas de esas versiones al modelo
  le fue igual de bien o mejor.

Si el modelo mejora a la referencia, sus bots entran en la incubadora (uno por moneda) y a partir de ahí
los juzga el comité como a cualquier otro. Si además no se distingue del ruido, entran marcados "a prueba".
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data, departamentos, miner, pipeline
from .backtest import Resultado, backtest, costes_de, metricas, tamano
from .data import velas_por_anio
from .store import Almacen

MODELOS = {
    "tendencia_conjunta": {
        "tf": "1d", "params": {"ventanas": "todas"},
        "fuente": "Zarattini, Pagani y Barbon (2025), «Catching Crypto Trends»",
        "resumen": "nueve modelos de canal de 5 a 360 días, solo largos, con un stop que solo sube",
    },
    "impulso_conjunto": {
        "tf": "1d", "params": {"ventanas": "1-3-12 meses"},
        "fuente": "impulso de serie temporal a 1, 3 y 12 meses (Moskowitz, Ooi y Pedersen, 2012), aplicado a cripto",
        "resumen": "dentro mientras el precio esté por encima del de hace uno, tres y doce meses",
    },
}
CLAVES = ("retorno", "cagr", "sharpe", "dd_max", "trades")


def universo(cfg: dict, tf: str) -> miner.Universo | None:
    """Cartera con todas las monedas que tienen bastante histórico en ese timeframe."""
    carpeta, ex, minimo = cfg["rutas"]["datos"], cfg["exchange"], cfg["biblioteca"]["velas_min"]
    dfs, fundings = {}, {}
    for s in cfg["simbolos"]:
        if not data.ruta_velas(carpeta, ex, s, tf).exists():
            continue
        df = data.cargar_velas(carpeta, ex, s, tf, config.historia(cfg, tf))
        if len(df) >= minimo:
            dfs[s] = df
            fundings[s] = data.funding_por_vela(df.index, tf, data.cargar_funding(carpeta, ex, s), cfg["costes"]["funding_8h"])
    return miner.Universo(dfs, fundings) if len(dfs) >= 4 else None


def referencia(u: miner.Universo, tf: str, cfg: dict) -> Resultado:
    """Comprar y mantener todas las monedas a partes iguales, reajustando el tamaño por volatilidad cada 30 velas."""
    n, peso = len(u), 1.0 / len(u.dfs)
    neto, pos, pnls = np.zeros(n), np.zeros(n), []
    for s, df in u.dfs.items():
        tam = pd.Series(tamano(df, tf, cfg["dimensionado"]))
        tam = tam.where(np.arange(len(df)) % 30 == 0).ffill().fillna(0.0).to_numpy()
        r = backtest(df, tam, tf, costes_de(cfg["costes"], s), {"vol_objetivo_anual": 0}, u.fundings.get(s))   # la "señal" ya es el tamaño
        idx = u.pos[s]
        dentro = idx >= 0
        np.add.at(neto, idx[dentro], r.neto[dentro] * peso)
        np.add.at(pos, idx[dentro], r.pos[dentro] * peso)
        pnls.append(r.trade_pnl * peso)
    return Resultado(u.indice, neto, pos, np.zeros(0, dtype=int), np.concatenate(pnls), velas_por_anio(tf))


def _resumen(res: Resultado) -> dict:
    m = metricas(res.neto, res.trade_pnl, res.vpa)
    return {**{k: m[k] for k in CLAVES}, "exposicion": float(res.pos.mean())}


def evaluar(nombre: str, u: miner.Universo, cfg: dict, rondas: int | None = None) -> dict:
    """Qué habría hecho el modelo en todo el histórico, frente a comprar y mantener y frente al ruido."""
    m = MODELOS[nombre]
    tf = m["tf"]
    rondas = cfg["biblioteca"]["rondas"] if rondas is None else rondas
    res, ref = miner.evaluar(u, tf, nombre, m["params"], cfg), referencia(u, tf, cfg)
    real = _resumen(res)
    falsos = []
    for k in range(rondas):
        r = miner.evaluar(pipeline._placebo(u, 104729 * (k + 1)), tf, nombre, m["params"], cfg)
        falsos.append(metricas(r.neto, r.trade_pnl, r.vpa)["sharpe"])
    p = (1 + sum(1 for x in falsos if x >= real["sharpe"])) / (rondas + 1) if rondas else None
    anual = lambda neto: (1.0 + pd.Series(neto, index=u.indice)).groupby(u.indice.year).prod() - 1.0
    a_mod, a_ref = anual(res.neto), anual(ref.neto)
    return {
        "nombre": nombre, "tf": tf, "fuente": m["fuente"], "resumen": m["resumen"], "simbolos": u.simbolos,
        "desde": str(u.indice[0].date()), "hasta": str(u.indice[-1].date()),
        "modelo": real, "referencia": _resumen(ref),
        "por_anio": [{"anio": int(y), "modelo": float(a_mod[y]), "referencia": float(a_ref[y])} for y in a_mod.index],
        "ruido": {"rondas": rondas, "sharpe_medio": float(np.mean(falsos)) if falsos else None,
                  "sharpe_p95": float(np.percentile(falsos, 95)) if falsos else None},
        "p_valor": p, "evidencia": bool(p is not None and p <= 0.10),
        "mejora": bool(real["sharpe"] > 0 and real["sharpe"] > _resumen(ref)["sharpe"]),
    }


def veredicto(r: dict) -> str:
    m, ref = r["modelo"], r["referencia"]
    base = (f"De {r['desde']} a {r['hasta']} en {len(r['simbolos'])} monedas: {m['cagr']:+.1%} al año con Sharpe {m['sharpe']:.2f} y caída máxima del "
            f"{m['dd_max']:.0%}; comprar y mantener con el mismo control de tamaño dio {ref['cagr']:+.1%} al año, Sharpe {ref['sharpe']:.2f} y caída del {ref['dd_max']:.0%}.")
    if r["p_valor"] is None:
        return base
    if r["evidencia"]:
        return base + f" Frente al ruido, p = {r['p_valor']:.2f}: mejor de lo que explica la suerte."
    return base + f" Frente al ruido, p = {r['p_valor']:.2f}: con este histórico no se distingue de la suerte."


def contratar(al: Almacen, cfg: dict, ahora: pd.Timestamp, aviso=None) -> int:
    """Evalúa los modelos de la biblioteca (como mucho una vez cada `cada_dias`) y manda a la incubadora los que
    mejoran a comprar y mantener. Las cuentas largas van antes de tocar la base, para no bloquearla."""
    nuevas, informe = 0, {}
    cfg = {**cfg, "costes": departamentos.costes_con_medidas(al, cfg)}      # simula con lo que cuesta de verdad operar cada moneda
    for nombre, m in MODELOS.items():
        previo = al.get(f"biblioteca:{nombre}")
        if previo and ahora - pd.Timestamp(previo["ts"]) < pd.Timedelta(days=cfg["biblioteca"]["cada_dias"]):
            continue
        u = universo(cfg, m["tf"])
        if u is None:
            continue
        r = evaluar(nombre, u, cfg)
        r["ts"], r["veredicto"] = str(ahora), veredicto(r)
        if aviso:
            aviso(f"{nombre}: {r['veredicto']}")
        dentro = 0
        if r["mejora"]:
            libres = max(0, cfg["incubadora"]["max_estrategias"] - al.contar("incubadora"))
            datos = {"origen": "publicado", "fuente": m["fuente"], "cartera": f"{nombre} {m['tf']}", "universo": u.simbolos,
                     "sin_evidencia": not r["evidencia"], "historico": r["modelo"]}
            for s in u.simbolos:
                if dentro >= libres:
                    break
                if al.alta_estrategia(s, m["tf"], nombre, m["params"], "incubadora", datos, ahora):
                    dentro += 1
        etiqueta = f"Modelo publicado {nombre.replace('_', ' ')} ({m['fuente']})"
        if dentro:
            al.evento(ahora, "Investigación", "alta", f"{etiqueta}: {dentro} bots entran en incubadora"
                      + ("" if r["evidencia"] else ", a prueba") + f". {r['veredicto']}")
        elif previo is None:
            al.evento(ahora, "Investigación", "aviso", f"{etiqueta}: " + ("no cabe nadie más en la incubadora. " if r["mejora"] else
                      "no mejora a comprar y mantener con nuestros datos, así que no se contrata. ") + r["veredicto"])
        r["bots"] = dentro + (previo or {}).get("bots", 0)
        al.set(f"biblioteca:{nombre}", r)
        al.commit()
        nuevas += dentro
        informe[nombre] = r
    if informe:
        carpeta = Path(cfg["rutas"]["informes"])
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "biblioteca.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    return nuevas


def estado(al: Almacen) -> list[dict]:
    return [r for n in MODELOS if (r := al.get(f"biblioteca:{n}"))]
