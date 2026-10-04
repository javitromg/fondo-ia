"""Familias de estrategias. Cada una devuelve la señal decidida al CIERRE de cada vela:
+1 largo, -1 corto, 0 fuera. El backtester la ejecuta en la apertura de la vela siguiente.

Para añadir una estrategia: escribe la función y regístrala con @estrategia(espacio).
Espacio de parámetros: ("int", min, max) | ("float", min, max) | ("cat", [opciones]).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Estrategia:
    nombre: str
    espacio: dict
    fn: Callable[[pd.DataFrame, dict], np.ndarray]
    fraccion: bool = False      # True: la señal puede valer cualquier cosa entre -1 y +1 (media de varios modelos)


REGISTRO: dict[str, Estrategia] = {}        # estrategias que miran un solo símbolo
TRANSVERSALES: dict[str, Estrategia] = {}   # estrategias que comparan varios símbolos entre sí (solo en modo cartera)
PUBLICADAS: dict[str, Estrategia] = {}      # modelos publicados con reglas fijas: no se minan, se contratan tal cual (biblioteca.py)
MODO = ("cat", ["largo_corto", "solo_largo"])


def buscar(nombre: str) -> Estrategia:
    for registro in (REGISTRO, TRANSVERSALES, PUBLICADAS):
        if nombre in registro:
            return registro[nombre]
    raise KeyError(nombre)


def publicada(espacio: dict):
    def deco(fn):
        PUBLICADAS[fn.__name__] = Estrategia(fn.__name__, espacio, fn, fraccion=True)
        return fn

    return deco


def transversal(espacio: dict):
    def deco(fn):
        TRANSVERSALES[fn.__name__] = Estrategia(fn.__name__, espacio, fn)
        return fn

    return deco


def cierres(dfs: dict) -> pd.DataFrame:
    """Cierres de todos los símbolos en una tabla común (una columna por símbolo, vacío antes de que cotice)."""
    return pd.concat({s: df["close"] for s, df in dfs.items()}, axis=1).sort_index()


def senal_transversal(nombre: str, dfs: dict, params: dict, tabla: pd.DataFrame | None = None) -> dict:
    """Señal de cada símbolo, alineada con sus propias velas. dfs: {simbolo: velas}."""
    sig = TRANSVERSALES[nombre].fn(cierres(dfs) if tabla is None else tabla, params)
    return {s: np.sign(sig[s].reindex(df.index).fillna(0.0).to_numpy()) for s, df in dfs.items()}


def estrategia(espacio: dict):
    def deco(fn):
        REGISTRO[fn.__name__] = Estrategia(fn.__name__, {**espacio, "modo": MODO}, fn)
        return fn

    return deco


def senal(nombre: str, df: pd.DataFrame, params: dict) -> np.ndarray:
    e = buscar(nombre)
    s = np.nan_to_num(np.asarray(e.fn(df, params), dtype=float))
    s = np.clip(s, -1.0, 1.0) if e.fraccion else np.sign(s)
    if params.get("modo") == "solo_largo":
        s = np.clip(s, 0, 1)
    return s


def muestrear(nombre: str, rng: np.random.Generator) -> dict:
    p = {}
    for k, (tipo, *r) in buscar(nombre).espacio.items():
        if tipo == "int":
            p[k] = int(rng.integers(r[0], r[1] + 1))
        elif tipo == "float":
            p[k] = round(float(rng.uniform(r[0], r[1])), 4)
        else:
            p[k] = r[0][int(rng.integers(len(r[0])))]
    return p


def vecinos(nombre: str, params: dict, pert: float) -> list[dict]:
    """Variantes con cada parámetro numérico movido ±pert. Sirve para ver si el resultado es un pico aislado."""
    out = []
    for k, (tipo, *r) in buscar(nombre).espacio.items():
        if tipo == "cat":
            continue
        for signo in (-1, 1):
            v = params[k] * (1 + signo * pert)
            if tipo == "int":
                v = int(round(v))
                if v == params[k]:
                    v = params[k] + signo
                v = int(min(max(v, r[0]), r[1]))
            else:
                v = round(float(min(max(v, r[0]), r[1])), 4)
            if v != params[k]:
                out.append({**params, k: v})
    return out


# ---------------------------------------------------------------- estrategias


@estrategia({"rapida": ("int", 5, 60), "ratio": ("float", 1.5, 6.0)})
def cruce_medias(df, p):
    c = df["close"]
    lenta = int(p["rapida"] * p["ratio"])
    return np.sign(ind.ema(c, p["rapida"]) - ind.ema(c, lenta))


@estrategia({"entrada": ("int", 20, 240), "salida_frac": ("float", 0.2, 0.8)})
def ruptura_donchian(df, p):
    c = df["close"]
    n, m = p["entrada"], max(2, int(p["entrada"] * p["salida_frac"]))
    arriba, abajo = ind.maximo(df["high"], n).shift(1), ind.minimo(df["low"], n).shift(1)
    sal_l, sal_c = ind.minimo(df["low"], m).shift(1), ind.maximo(df["high"], m).shift(1)
    largo = ind.mantener((c > arriba).to_numpy(), (c < sal_l).to_numpy(), 1.0)
    corto = ind.mantener((c < abajo).to_numpy(), (c > sal_c).to_numpy(), -1.0)
    return largo + corto


@estrategia({"n": ("int", 2, 21), "umbral": ("int", 10, 35), "filtro": ("cat", [0, 100, 200])})
def rsi_reversion(df, p):
    c = df["close"]
    r = ind.rsi(c, p["n"])
    ok_l = ok_c = pd.Series(True, index=c.index)
    if p["filtro"]:
        media = ind.sma(c, p["filtro"])
        ok_l, ok_c = c > media, c < media
    largo = ind.mantener(((r < p["umbral"]) & ok_l).to_numpy(), (r > 50).to_numpy(), 1.0)
    corto = ind.mantener(((r > 100 - p["umbral"]) & ok_c).to_numpy(), (r < 50).to_numpy(), -1.0)
    return largo + corto


@estrategia({"n": ("int", 10, 80), "k": ("float", 1.5, 3.0)})
def bollinger_reversion(df, p):
    c = df["close"]
    media, desv = ind.sma(c, p["n"]), c.rolling(p["n"], min_periods=p["n"]).std()
    largo = ind.mantener((c < media - p["k"] * desv).to_numpy(), (c >= media).to_numpy(), 1.0)
    corto = ind.mantener((c > media + p["k"] * desv).to_numpy(), (c <= media).to_numpy(), -1.0)
    return largo + corto


@estrategia({"tenkan": ("int", 5, 20), "ratio_kijun": ("float", 2.0, 4.0)})
def ichimoku(df, p):
    c = df["close"]
    t, k = p["tenkan"], int(p["tenkan"] * p["ratio_kijun"])
    medio = lambda n: (ind.maximo(df["high"], n) + ind.minimo(df["low"], n)) / 2
    tenkan, kijun = medio(t), medio(k)
    # la nube visible hoy se calculó hace `k` velas
    span_a, span_b = ((tenkan + kijun) / 2).shift(k), medio(2 * k).shift(k)
    techo, suelo = np.maximum(span_a, span_b), np.minimum(span_a, span_b)
    largo = (c > techo) & (tenkan > kijun)
    corto = (c < suelo) & (tenkan < kijun)
    return largo.astype(float) - corto.astype(float)


@estrategia({"ventana": ("int", 24, 720), "umbral": ("float", 0.0, 0.06)})
def momentum(df, p):
    r = df["close"].pct_change(p["ventana"])
    return (r > p["umbral"]).astype(float) - (r < -p["umbral"]).astype(float)


@estrategia({"rapida": ("int", 6, 24), "ratio": ("float", 1.8, 3.5), "suavizado": ("int", 5, 15)})
def macd(df, p):
    c = df["close"]
    linea = ind.ema(c, p["rapida"]) - ind.ema(c, int(p["rapida"] * p["ratio"]))
    return np.sign(linea - ind.ema(linea, p["suavizado"]))


@estrategia({"n": ("int", 10, 100), "mult": ("float", 1.0, 4.0)})
def canal_keltner(df, p):
    c = df["close"]
    media, rango = ind.ema(c, p["n"]), ind.atr(df, p["n"])
    largo = ind.mantener((c > media + p["mult"] * rango).to_numpy(), (c < media).to_numpy(), 1.0)
    corto = ind.mantener((c < media - p["mult"] * rango).to_numpy(), (c > media).to_numpy(), -1.0)
    return largo + corto


@estrategia({"hora": ("int", 0, 23), "duracion": ("int", 1, 8), "sentido": ("cat", [1, -1])})
def hora_del_dia(df, p):
    """Patrón de horario: estar dentro solo durante una franja fija del día (hora UTC)."""
    dentro = ((df.index.hour - p["hora"]) % 24) < p["duracion"]
    return np.where(dentro, float(p["sentido"]), 0.0)


# ---------------------------------------------------------------- transversales


@transversal({"ventana": ("int", 24, 720), "espera": ("int", 1, 48), "fraccion": ("float", 0.15, 0.4),
              "sentido": ("cat", ["ganadoras", "perdedoras"])})
def fuerza_relativa(tabla, p):
    """Ordena las monedas por lo que han subido en la ventana y se pone larga en un extremo y corta en el otro.

    "ganadoras": compra las que más suben y vende las que menos (la fuerza continúa).
    "perdedoras": al revés (lo que más ha subido se da la vuelta).
    Al ir larga y corta a la vez, apenas depende de si el mercado en general sube o baja.
    La cartera se revisa cada `espera` velas, contadas desde una fecha fija para que el
    resultado no dependa de cuántas velas de historia se carguen.
    """
    cambio = tabla / tabla.shift(p["ventana"]) - 1.0
    puesto = cambio.rank(axis=1, pct=True)
    vivos = cambio.notna().sum(axis=1)
    sig = (puesto > 1 - p["fraccion"]).astype(float) - (puesto <= p["fraccion"]).astype(float)
    sig[vivos < 4] = 0.0
    if p["sentido"] == "perdedoras":
        sig = -sig
    if len(tabla) > 1:
        paso = pd.Series(tabla.index[1:] - tabla.index[:-1]).mode()[0]
        toca = ((tabla.index - pd.Timestamp(0, tz=tabla.index.tz)) // paso) % p["espera"] == 0
        sig = sig.where(pd.Series(toca, index=tabla.index), axis=0).ffill().fillna(0.0)
    return sig.where(cambio.notna(), 0.0)


# ---------------------------------------------------------------- publicadas

VENTANAS_TENDENCIA = (5, 10, 20, 30, 60, 90, 150, 250, 360)


def _canal_con_stop(c: np.ndarray, n: int) -> np.ndarray:
    """Un modelo de canal: entra cuando el cierre marca máximo de `n` velas y sale con un stop que solo sube,
    colocado en el punto medio del canal (media entre el máximo y el mínimo de cierres de `n` velas)."""
    serie = pd.Series(c)
    alto = serie.rolling(n, min_periods=n).max().to_numpy()
    medio = (alto + serie.rolling(n, min_periods=n).min().to_numpy()) / 2.0
    out, dentro, stop = np.zeros(len(c)), False, 0.0
    for i in range(n - 1, len(c)):
        if dentro:
            stop = max(stop, medio[i])
            dentro = c[i] >= stop
        elif c[i] >= alto[i]:
            dentro, stop = True, medio[i]
        out[i] = 1.0 if dentro else 0.0
    return out


@publicada({"ventanas": ("cat", ["todas"])})
def tendencia_conjunta(df, p):
    """Conjunto de nueve modelos de tendencia de canal, solo largos (Zarattini, Pagani y Barbon, 2025).

    Cada modelo mira una ventana distinta, de 5 a 360 velas, y vota 1 (dentro) o 0 (fuera). La señal es la
    media de los votos: con los nueve dentro se invierte todo el tamaño; con tres, un tercio. Pensado para
    velas diarias. No tiene parámetros que afinar, y por eso no se mina: se usa tal como está publicado.
    """
    c = df["close"].to_numpy(dtype=float)
    return np.mean([_canal_con_stop(c, n) for n in VENTANAS_TENDENCIA], axis=0)


VENTANAS_IMPULSO = (30, 90, 365)


@publicada({"ventanas": ("cat", ["1-3-12 meses"])})
def impulso_conjunto(df, p):
    """Impulso a uno, tres y doce meses, solo largo (la versión clásica de los fondos de tendencia).

    Cada ventana vota 1 si el precio está por encima del de hace 30, 90 o 365 velas, y la señal es la media.
    Pensado para velas diarias. Sin parámetros que afinar.
    """
    c = df["close"]
    return np.mean([(c > c.shift(n)).to_numpy(dtype=float) for n in VENTANAS_IMPULSO], axis=0)
