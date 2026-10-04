"""Datos de mercado: descarga con ccxt, caché en disco y series sintéticas para pruebas."""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}
COLUMNAS = ["open", "high", "low", "close", "volume"]


def velas_por_anio(tf: str) -> float:
    return 365.0 * 24 * 60 / TF_MIN[tf]


def _nombre(simbolo: str) -> str:
    return simbolo.replace("/", "-").replace(":", "_")


def ruta_velas(carpeta, exchange: str, simbolo: str, tf: str) -> Path:
    return Path(carpeta) / exchange / f"{_nombre(simbolo)}_{tf}.parquet"


def ruta_funding(carpeta, exchange: str, simbolo: str) -> Path:
    return Path(carpeta) / exchange / f"{_nombre(simbolo)}_funding.parquet"


def crear_exchange(exchange_id: str):
    import ccxt

    return getattr(ccxt, exchange_id)({"enableRateLimit": True})


def _a_df(filas) -> pd.DataFrame:
    df = pd.DataFrame(filas, columns=["ts", *COLUMNAS])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    return df.astype(float)


def _guardar(df: pd.DataFrame, ruta: Path):
    """Escribe en un temporal y lo renombra: si dos procesos coinciden, nadie lee un archivo a medias."""
    tmp = ruta.with_name(ruta.name + f".{os.getpid()}.tmp")
    df.to_parquet(tmp)
    os.replace(tmp, ruta)


def descargar_velas(ex, simbolo: str, tf: str, dias: int, carpeta, exchange_id: str, ahora_ms: int | None = None) -> pd.DataFrame:
    """Descarga (o actualiza) velas cerradas y las guarda en parquet."""
    ruta = ruta_velas(carpeta, exchange_id, simbolo, tf)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tf_ms = TF_MIN[tf] * 60_000
    ahora_ms = ahora_ms or int(time.time() * 1000)
    previo = pd.read_parquet(ruta) if ruta.exists() else None
    if previo is not None and len(previo):
        desde = int(previo.index[-1].timestamp() * 1000) + tf_ms
    else:
        desde = ahora_ms - dias * 86_400_000
    filas = []
    while desde < ahora_ms:
        lote = ex.fetch_ohlcv(simbolo, tf, since=desde, limit=1000)
        if not lote:
            desde += 1000 * tf_ms     # ventana vacía (p. ej. antes de que el contrato existiera): se salta
            continue
        filas.extend(lote)
        desde = max(lote[-1][0] + tf_ms, desde + tf_ms)
    nuevo = _a_df(filas) if filas else None
    df = pd.concat([x for x in (previo, nuevo) if x is not None]) if (previo is not None or nuevo is not None) else _a_df([])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    # fuera la vela que aún no ha cerrado
    limite = pd.Timestamp(ahora_ms - tf_ms, unit="ms", tz="UTC")
    df = df[df.index <= limite]
    _guardar(df, ruta)
    return df


def descargar_funding(ex, simbolo: str, dias: int, carpeta, exchange_id: str, ahora_ms: int | None = None) -> pd.Series | None:
    """Histórico de funding. Si el exchange no lo da, devuelve None y se usa el valor fijo de config."""
    ruta = ruta_funding(carpeta, exchange_id, simbolo)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ahora_ms = ahora_ms or int(time.time() * 1000)
    desde = ahora_ms - dias * 86_400_000
    filas = {}
    try:
        while desde < ahora_ms:
            lote = ex.fetch_funding_rate_history(simbolo, since=desde, limit=200)
            if not lote:
                break
            for x in lote:
                filas[x["timestamp"]] = x["fundingRate"]
            ultimo = max(x["timestamp"] for x in lote)
            if ultimo + 1 <= desde:
                break
            desde = ultimo + 1
    except Exception:
        if not filas:
            return None
    if not filas:
        return None
    s = pd.Series(filas).sort_index()
    s.index = pd.to_datetime(s.index, unit="ms", utc=True)
    s.name = "funding"
    _guardar(s.to_frame(), ruta)
    return s


def cargar_velas(carpeta, exchange_id: str, simbolo: str, tf: str, dias: int | None = None) -> pd.DataFrame:
    """Velas guardadas. Con `dias`, solo la ventana más reciente: así cada minería trabaja con lo último."""
    df = pd.read_parquet(ruta_velas(carpeta, exchange_id, simbolo, tf))
    if dias and len(df):
        df = df[df.index >= df.index[-1] - pd.Timedelta(days=dias)]
    return df


def perpetuos_disponibles(ex) -> list[str]:
    """Símbolos de perpetuos lineales que ofrece el exchange (para corregir config.yaml si un símbolo no existe)."""
    mercados = ex.load_markets()
    return sorted(s for s, m in mercados.items() if m.get("swap") and m.get("linear") and m.get("active", True))


def cargar_funding(carpeta, exchange_id: str, simbolo: str) -> pd.Series | None:
    ruta = ruta_funding(carpeta, exchange_id, simbolo)
    if not ruta.exists():
        return None
    return pd.read_parquet(ruta)["funding"]


def funding_por_vela(indice: pd.DatetimeIndex, tf: str, funding: pd.Series | None, fijo_8h: float) -> np.ndarray:
    """Funding que paga un largo en cada vela (tanto por uno). Con histórico real si lo hay."""
    if funding is None or len(funding) == 0:
        return np.full(len(indice), fijo_8h * TF_MIN[tf] / 480.0)
    por_vela = funding.groupby(funding.index.floor(f"{TF_MIN[tf]}min")).sum()
    out = por_vela.reindex(indice).fillna(0.0).to_numpy(copy=True)
    # fuera del rango cubierto por el histórico, valor fijo
    fuera = (indice < funding.index[0]) | (indice > funding.index[-1])
    out[fuera] = fijo_8h * TF_MIN[tf] / 480.0
    return out


def sintetico(n: int = 20000, tipo: str = "aleatorio", tf: str = "1h", semilla: int = 0, precio0: float = 100.0) -> pd.DataFrame:
    """Serie sintética para comprobar el motor.

    - "aleatorio": paseo aleatorio con colas gordas. Aquí NO hay ventaja: nada debería sobrevivir.
    - "tendencial": tendencias persistentes que cambian de signo. Aquí SÍ hay ventaja para seguir tendencia.
    """
    rng = np.random.default_rng(semilla)
    ruido = rng.standard_t(df=4, size=n) / np.sqrt(2.0) * 0.005
    if tipo == "aleatorio":
        deriva = np.zeros(n)
    elif tipo == "tendencial":
        deriva = np.empty(n)
        i, signo = 0, 1.0
        while i < n:
            largo = int(rng.geometric(1 / 300.0))
            deriva[i : i + largo] = signo * 0.0003
            signo, i = -signo, i + largo
    else:
        raise ValueError(tipo)
    ret = deriva + ruido
    close = precio0 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[precio0], close[:-1]])
    mecha = np.abs(rng.normal(0, 0.0015, size=(2, n)))
    high = np.maximum(open_, close) * (1 + mecha[0])
    low = np.minimum(open_, close) * (1 - mecha[1])
    idx = pd.date_range("2022-01-01", periods=n, freq=f"{TF_MIN[tf]}min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.uniform(100, 1000, n)}, index=idx)


def ruido(df: pd.DataFrame, semilla: int = 0, signos: pd.Series | None = None) -> pd.DataFrame:
    """Versión "placebo" de una serie real: invierte al azar cada vela alrededor de la subida media.

    Conserva el tamaño de los movimientos, las rachas de volatilidad y lo que el activo subió o bajó
    en total, pero destruye cualquier patrón sobre CUÁNDO se mueve. Así, una estrategia que solo gana
    por estar comprada en un mercado alcista gana lo mismo en el placebo y no cuenta como hallazgo.
    Con `signos` (una serie de +1/-1 por fecha) varias series se invierten a la vez, de modo que
    siguen moviéndose juntas igual que en la realidad.
    """
    rng = np.random.default_rng(semilla)
    pc = df["close"].shift(1).fillna(df["open"].iloc[0]).to_numpy()
    lo, lh, ll, lc = (np.log(df[k].to_numpy() / pc) for k in ("open", "high", "low", "close"))
    s = rng.choice([-1.0, 1.0], size=len(df)) if signos is None else signos.reindex(df.index).fillna(1.0).to_numpy()
    mu = lc.mean()
    esp = lambda x: 2 * mu - x          # espejo alrededor de la deriva media
    lo2, lc2 = np.where(s > 0, lo, esp(lo)), np.where(s > 0, lc, esp(lc))
    lh2, ll2 = np.where(s > 0, lh, esp(ll)), np.where(s > 0, ll, esp(lh))
    close = df["open"].iloc[0] * np.exp(np.cumsum(lc2))
    pc2 = np.concatenate([[df["open"].iloc[0]], close[:-1]])
    return pd.DataFrame({"open": pc2 * np.exp(lo2), "high": pc2 * np.exp(lh2), "low": pc2 * np.exp(ll2),
                         "close": close, "volume": df["volume"].to_numpy()}, index=df.index)
