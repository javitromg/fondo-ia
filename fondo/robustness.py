"""Embudo de robustez. Una candidata tiene que pasar TODOS los filtros, en este orden:

1. validacion     — sigue funcionando en datos que la minería no vio.
2. tramos         — gana en la mayoría de trozos del histórico, no solo en una racha.
3. montecarlo     — remuestreando sus operaciones, el caso malo (percentil 5) sigue en positivo.
4. vecindad       — moviendo un poco los parámetros no se hunde (no es un pico de sobreajuste).
5. estres_costes  — aguanta con el doble de comisiones y slippage.
6. reserva        — tramo final intacto, se mira una única vez y al final.

Además se calcula el Sharpe deflactado (DSR) de cada candidata como dato informativo; solo
actúa de filtro si pones robustez.dsr_min > 0. La corrección por "haber probado miles de
combinaciones" la hace el control de ruido de pipeline.py, que es empírico y no teórico.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from . import strategies as st
from .backtest import metricas_tramo
from .miner import cortes, evaluar

_N = NormalDist()
_EULER = 0.5772156649015329
FILTROS = ["validacion", "tramos", "montecarlo", "vecindad", "estres_costes", "dsr", "reserva"]  # "dsr" solo si dsr_min > 0


def sharpe_deflactado(neto: np.ndarray, n_pruebas: int, var_sharpe: float) -> float:
    """Probabilidad de que el Sharpe real sea > 0 tras corregir por selección (Bailey y López de Prado)."""
    t = len(neto)
    sd = neto.std(ddof=1)
    if t < 30 or sd == 0:
        return 0.0
    sr = neto.mean() / sd
    z = (neto - neto.mean()) / sd
    asim, curt = float((z**3).mean()), float((z**4).mean())
    n = max(int(n_pruebas), 2)
    var = min(var_sharpe, 1.0 / (t - 1)) if var_sharpe > 0 else 1.0 / (t - 1)   # sin ventaja, el Sharpe no varía más que su error muestral
    sr0 = math.sqrt(var) * ((1 - _EULER) * _N.inv_cdf(1 - 1 / n) + _EULER * _N.inv_cdf(1 - 1 / (n * math.e)))
    den = 1 - asim * sr + (curt - 1) / 4 * sr**2
    if den <= 0:
        return 0.0
    return float(_N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(den)))


def montecarlo(trade_pnl: np.ndarray, simulaciones: int, semilla: int = 0) -> dict:
    """Remuestreo con reposición de las operaciones: distribución del retorno final y de la caída máxima."""
    if len(trade_pnl) < 5:
        return {"p5_retorno": -1.0, "p95_dd": 1.0}
    rng = np.random.default_rng(semilla)
    m = rng.choice(trade_pnl, size=(simulaciones, len(trade_pnl)), replace=True)
    eq = np.cumprod(1.0 + np.clip(m, -0.99, None), axis=1)
    pico = np.maximum.accumulate(np.maximum(eq, 1.0), axis=1)
    return {"p5_retorno": float(np.percentile(eq[:, -1] - 1.0, 5)), "p95_dd": float(np.percentile((1 - eq / pico).max(axis=1), 95))}


def validar(cand: dict, df, tf: str, cfg: dict, funding_vela, n_pruebas: int, var_sharpe: float) -> dict:
    r, m = cfg["robustez"], cfg["mineria"]
    i_val, i_res = cortes(len(df), m["tramos"])
    nombre, params = cand["nombre"], cand["params"]
    sim = cand["simbolo"]
    res = evaluar(df, tf, nombre, params, cfg, funding_vela, simbolo=sim)
    me, mv = metricas_tramo(res, 0, i_val), metricas_tramo(res, i_val, i_res)
    visto = metricas_tramo(res, 0, i_res)     # entrenamiento + validación; la reserva no entra aquí
    pasos, detalle = {}, {}
    dsr = sharpe_deflactado(res.neto[:i_val], n_pruebas, var_sharpe)

    def paso(nombre_paso: str, ok: bool, info: dict) -> bool:
        pasos[nombre_paso], detalle[nombre_paso] = bool(ok), info
        return bool(ok)

    def resultado(sobrevive: bool, mr: dict | None = None) -> dict:
        eq = np.cumprod(1 + res.neto[:i_res] if mr is None else 1 + res.neto)
        salto = max(1, len(eq) // 300)
        return {**cand, "entrenamiento": me, "validacion": mv, "reserva": mr, "pasos": pasos, "detalle": detalle, "dsr": dsr,
                "sobrevive": sobrevive, "caida_en": None if sobrevive else next(k for k in FILTROS if pasos.get(k) is False),
                "curva": [round(float(x), 4) for x in eq[::salto]], "cortes": [i_val // salto, i_res // salto]}

    v = r["validacion"]
    retencion = mv["sharpe"] / me["sharpe"] if me["sharpe"] > 0 else 0.0
    if not paso("validacion", mv["sharpe"] >= v["sharpe_min"] and mv["pf"] >= v["pf_min"] and retencion >= v["retencion_min"],
                {"sharpe": mv["sharpe"], "pf": mv["pf"], "retencion": retencion}):
        return resultado(False)

    n = r["tramos"]["n"]
    bordes = np.linspace(0, i_res, n + 1).astype(int)
    positivos = float(np.mean([np.prod(1 + res.neto[a:b]) > 1 for a, b in zip(bordes[:-1], bordes[1:])]))
    if not paso("tramos", positivos >= r["tramos"]["pct_positivos_min"], {"pct_positivos": positivos}):
        return resultado(False)

    mc_cfg = r["montecarlo"]
    mc = montecarlo(res.trade_pnl[res.trade_inicio < i_res], mc_cfg["simulaciones"], m["semilla"])
    if not paso("montecarlo", mc["p5_retorno"] >= mc_cfg["p5_retorno_min"] and mc["p95_dd"] <= mc_cfg["p95_dd_max"], mc):
        return resultado(False)

    vc = r["vecindad"]
    sh = [metricas_tramo(evaluar(df, tf, nombre, p, cfg, funding_vela, simbolo=sim), 0, i_res) for p in st.vecinos(nombre, params, vc["perturbacion"])]
    pct = float(np.mean([x["retorno"] > 0 for x in sh])) if sh else 0.0
    ret_med = float(np.median([x["sharpe"] for x in sh]) / visto["sharpe"]) if sh and visto["sharpe"] > 0 else 0.0
    if not paso("vecindad", pct >= vc["pct_rentables_min"] and ret_med >= vc["retencion_mediana_min"],
                {"pct_rentables": pct, "retencion_mediana": ret_med, "vecinos": len(sh)}):
        return resultado(False)

    caro = metricas_tramo(evaluar(df, tf, nombre, params, cfg, funding_vela, r["estres_costes"]["multiplicador"], simbolo=sim), 0, i_res)
    if not paso("estres_costes", caro["retorno"] > 0, {"retorno": caro["retorno"], "sharpe": caro["sharpe"]}):
        return resultado(False)

    if r.get("dsr_min", 0) > 0 and not paso("dsr", dsr >= r["dsr_min"], {"dsr": dsr, "pruebas": n_pruebas}):
        return resultado(False)

    mr = metricas_tramo(res, i_res, len(df))
    rv = r["reserva"]
    ok = paso("reserva", mr["sharpe"] >= rv["sharpe_min"] and mr["pf"] >= rv["pf_min"] and mr["retorno"] > 0,
              {"sharpe": mr["sharpe"], "pf": mr["pf"], "retorno": mr["retorno"]})
    return resultado(ok, mr)


ETIQUETAS = {"validacion": "validación", "tramos": "consistencia por tramos", "montecarlo": "Monte Carlo",
             "vecindad": "vecindad de parámetros", "estres_costes": "estrés de costes", "dsr": "Sharpe deflactado", "reserva": "reserva"}


def embudo(resultados: list[dict], pruebas: int) -> list[tuple[str, int]]:
    """Cuántas quedan vivas tras cada filtro."""
    filas = [("combinaciones probadas", pruebas), ("pasan entrenamiento", len(resultados))]
    for f in FILTROS:
        if f == "dsr" and not any("dsr" in x["pasos"] for x in resultados):
            continue
        filas.append((f"pasan {ETIQUETAS[f]}", sum(1 for x in resultados if x["pasos"].get(f))))
    return filas
