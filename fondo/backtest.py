"""Backtester vectorizado para perpetuos.

Reglas (las mismas que sigue la incubadora en vivo):
- La señal se decide al cierre de la vela t y se ejecuta en la apertura de t+1.
- El tamaño se fija al abrir la operación (volatilidad objetivo, con tope de apalancamiento)
  y no se toca hasta que cambia la señal.
- Cada cambio de posición paga comisión + slippage sobre el nominal movido.
- Los largos pagan funding cuando es positivo y lo cobran cuando es negativo (los cortos al revés).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import TF_MIN, velas_por_anio


@dataclass
class Resultado:
    indice: pd.DatetimeIndex
    neto: np.ndarray          # retorno neto por vela (tanto por uno sobre el capital)
    pos: np.ndarray           # exposición mantenida durante cada vela (múltiplo del capital)
    trade_inicio: np.ndarray  # índice de la vela de entrada de cada operación
    trade_pnl: np.ndarray     # resultado neto de cada operación
    vpa: float                # velas por año


def costes_de(costes: dict, simbolo: str | None) -> dict:
    """Costes de una moneda concreta: si Ejecución midió que cruzar su mercado cuesta más de lo supuesto, se usa lo medido."""
    medido = (costes.get("por_simbolo") or {}).get(simbolo)
    return costes if medido is None else {**costes, "slippage": max(costes["slippage"], medido)}


def tamano(df: pd.DataFrame, tf: str, dim: dict) -> np.ndarray:
    """Exposición que tocaría abrir en cada vela para apuntar a la volatilidad objetivo."""
    if not dim.get("vol_objetivo_anual"):
        return np.ones(len(df))
    vol = df["close"].pct_change().rolling(dim["ventana_vol"], min_periods=dim["ventana_vol"]).std() * np.sqrt(velas_por_anio(tf))
    t = (dim["vol_objetivo_anual"] / vol).clip(upper=dim["apalancamiento_max"])
    return t.replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy()


def backtest(df: pd.DataFrame, sig: np.ndarray, tf: str, costes: dict, dim: dict,
             funding_vela: np.ndarray | None = None, mult_costes: float = 1.0) -> Resultado:
    n = len(df)
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    sig = np.asarray(sig, dtype=float)

    cambio_sig = sig != np.concatenate([[0.0], sig[:-1]])
    tam = pd.Series(np.where(cambio_sig, tamano(df, tf, dim), np.nan)).ffill().fillna(0.0).to_numpy()
    objetivo = sig * tam

    pos = np.concatenate([[0.0], objetivo[:-1]])           # lo decidido en t-1 se mantiene durante t
    prev = np.concatenate([[0.0], pos[:-1]])
    ret = np.concatenate([o[1:] / o[:-1] - 1.0, [c[-1] / o[-1] - 1.0]])  # de apertura a apertura

    coste = (costes["comision"] + costes["slippage"]) * mult_costes
    if funding_vela is None:
        funding_vela = np.full(n, costes.get("funding_8h", 0.0) * TF_MIN[tf] / 480.0)
    bruto = pos * ret
    fund = pos * funding_vela
    neto = bruto - np.abs(pos - prev) * coste - fund

    # operaciones: cada tramo con posición distinta de cero
    cambio = pos != prev
    seg = np.cumsum(cambio)
    nseg = int(seg[-1]) + 1
    pnl = np.bincount(seg, weights=bruto - fund - np.abs(pos) * cambio * coste, minlength=nseg)
    idx = np.nonzero(cambio)[0]
    np.add.at(pnl, seg[idx] - 1, -np.abs(prev[idx]) * coste)   # el coste de cerrar va a la operación que se cierra
    pos_seg = np.zeros(nseg)
    pos_seg[seg[idx]] = pos[idx]
    inicio = np.zeros(nseg, dtype=int)
    inicio[seg[idx]] = idx
    activo = pos_seg != 0
    return Resultado(df.index, neto, pos, inicio[activo], pnl[activo], velas_por_anio(tf))


def metricas(neto: np.ndarray, trade_pnl: np.ndarray, vpa: float) -> dict:
    n = len(neto)
    if n < 2:
        return {"retorno": 0.0, "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "dd_max": 0.0, "pf": 0.0, "aciertos": 0.0, "trades": 0}
    eq = np.cumprod(1.0 + neto)
    pico = np.maximum.accumulate(np.maximum(eq, 1.0))
    sd = neto.std(ddof=1)
    neg = neto[neto < 0]
    sd_neg = np.sqrt((neg**2).sum() / n) if len(neg) else 0.0
    gan, per = trade_pnl[trade_pnl > 0].sum(), -trade_pnl[trade_pnl < 0].sum()
    return {
        "retorno": float(eq[-1] - 1.0),
        "cagr": float(eq[-1] ** (vpa / n) - 1.0) if eq[-1] > 0 else -1.0,
        "sharpe": float(neto.mean() / sd * np.sqrt(vpa)) if sd > 0 else 0.0,
        "sortino": float(neto.mean() / sd_neg * np.sqrt(vpa)) if sd_neg > 0 else 0.0,
        "dd_max": float((1.0 - eq / pico).max()),
        "pf": float(min(gan / per, 99.0)) if per > 0 else (99.0 if gan > 0 else 0.0),
        "aciertos": float((trade_pnl > 0).mean()) if len(trade_pnl) else 0.0,
        "trades": int(len(trade_pnl)),
    }


def metricas_tramo(res: Resultado, i0: int, i1: int) -> dict:
    """Métricas solo de las velas [i0, i1) y de las operaciones abiertas en ese tramo."""
    m = (res.trade_inicio >= i0) & (res.trade_inicio < i1)
    return metricas(res.neto[i0:i1], res.trade_pnl[m], res.vpa)
