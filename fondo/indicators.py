"""Indicadores. Todos son causales: el valor en t solo usa datos hasta t."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    sube = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    baja = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = sube / baja.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(baja != 0, 100.0).where(sube.notna())


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    cp = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - cp).abs(), (df["low"] - cp).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def maximo(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).max()


def minimo(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).min()


def mantener(entrada: np.ndarray, salida: np.ndarray, valor: float) -> np.ndarray:
    """Máquina de estados vectorizada: `valor` desde que hay entrada hasta que hay salida."""
    bruto = np.where(entrada, valor, np.where(salida, 0.0, np.nan))
    return pd.Series(bruto).ffill().fillna(0.0).to_numpy()
