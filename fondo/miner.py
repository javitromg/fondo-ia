"""Minería de estrategias: prueba miles de combinaciones mirando SOLO el tramo de entrenamiento."""
from __future__ import annotations

import numpy as np

import pandas as pd

from . import strategies as st
from .backtest import Resultado, backtest, costes_de, metricas_tramo
from .data import velas_por_anio

CARTERA = "CARTERA"


class Universo:
    """Varios símbolos del mismo timeframe tratados como una sola cartera.

    Una estrategia de cartera usa los MISMOS parámetros en todos los símbolos y reparte el capital
    a partes iguales. Es mucho más difícil de sobreajustar que una estrategia afinada para un único
    símbolo: un juego de parámetros tiene que funcionar en todos a la vez.
    """

    def __init__(self, dfs: dict, fundings: dict | None = None):
        self.dfs, self.fundings = dfs, fundings or {}
        union = sorted(set().union(*[df.index for df in dfs.values()]))
        # la cartera empieza cuando ya cotiza al menos el 60 % de los símbolos
        inicios = sorted(df.index[0] for df in dfs.values())
        desde = inicios[max(0, int(len(inicios) * 0.6 + 0.999) - 1)]
        self.indice = pd.DatetimeIndex([t for t in union if t >= desde])
        self.pos = {s: self.indice.get_indexer(df.index) for s, df in dfs.items()}   # -1 = fuera del tramo común
        self._tabla = None

    @property
    def tabla(self) -> pd.DataFrame:
        if self._tabla is None:
            self._tabla = st.cierres(self.dfs)
        return self._tabla

    def __len__(self):
        return len(self.indice)

    @property
    def simbolos(self) -> list[str]:
        return list(self.dfs)


def _evaluar_cartera(u: Universo, tf: str, nombre: str, params: dict, cfg: dict, mult_costes: float) -> Resultado:
    n, peso = len(u), 1.0 / len(u.dfs)
    neto, pos, inicios, pnls = np.zeros(n), np.zeros(n), [], []
    comunes = st.senal_transversal(nombre, u.dfs, params, u.tabla) if nombre in st.TRANSVERSALES else None
    for s, df in u.dfs.items():
        sig = comunes[s] if comunes is not None else st.senal(nombre, df, params)
        r = backtest(df, sig, tf, costes_de(cfg["costes"], s), cfg["dimensionado"], u.fundings.get(s), mult_costes)
        idx = u.pos[s]
        dentro = idx >= 0
        np.add.at(neto, idx[dentro], r.neto[dentro] * peso)
        np.add.at(pos, idx[dentro], r.pos[dentro] * peso)
        ok = dentro[r.trade_inicio]
        inicios.append(idx[r.trade_inicio[ok]])
        pnls.append(r.trade_pnl[ok] * peso)
    return Resultado(u.indice, neto, pos, np.concatenate(inicios), np.concatenate(pnls), velas_por_anio(tf))


def cortes(n: int, tramos: dict) -> tuple[int, int]:
    """Índices donde empiezan validación y reserva. Entrenamiento = [0, i_val)."""
    i_val = int(n * tramos["entrenamiento"])
    i_res = int(n * (tramos["entrenamiento"] + tramos["validacion"]))
    return i_val, i_res


def evaluar(df, tf: str, nombre: str, params: dict, cfg: dict, funding_vela=None, mult_costes: float = 1.0, simbolo: str | None = None) -> Resultado:
    if isinstance(df, Universo):
        return _evaluar_cartera(df, tf, nombre, params, cfg, mult_costes)
    return backtest(df, st.senal(nombre, df, params), tf, costes_de(cfg["costes"], simbolo), cfg["dimensionado"], funding_vela, mult_costes)


def minar(datos: dict, cfg: dict, progreso=None, pesos: dict | None = None) -> dict:
    """datos: {(simbolo, tf): (df, funding_vela | None)}.

    Devuelve las candidatas que pasan los filtros de entrenamiento, el número total de
    pruebas y la varianza de sus Sharpe (hacen falta para el Sharpe deflactado).
    """
    m = cfg["mineria"]
    f = m["filtros"]
    rng = np.random.default_rng(m["semilla"])
    candidatas, sharpes_vela, pruebas, por_familia = [], [], 0, {}
    pesos = pesos or {}
    for (simbolo, tf), (df, funding_vela) in datos.items():
        i_val, _ = cortes(len(df), m["tramos"])
        cartera = isinstance(df, Universo)
        for nombre in list(st.REGISTRO) + (list(st.TRANSVERSALES) if cartera else []):
            grupo, vistos = [], set()
            base = m.get("pruebas_cartera", 150) if cartera else m["pruebas_por_estrategia"]
            cuenta = por_familia.setdefault(nombre, {"pruebas": 0, "candidatas": 0})
            for _ in range(max(1, round(base * pesos.get(nombre, 1.0)))):
                params = st.muestrear(nombre, rng)
                clave = tuple(sorted(params.items()))
                if clave in vistos:
                    continue
                vistos.add(clave)
                res = evaluar(df, tf, nombre, params, cfg, funding_vela, simbolo=simbolo)
                pruebas += 1
                cuenta["pruebas"] += 1
                neto = res.neto[:i_val]
                sd = neto.std(ddof=1)
                sharpes_vela.append(neto.mean() / sd if sd > 0 else 0.0)
                me = metricas_tramo(res, 0, i_val)
                if (me["trades"] >= f["trades_min"] and me["sharpe"] >= f["sharpe_min"]
                        and me["pf"] >= f["pf_min"] and me["dd_max"] <= f["dd_max"]):
                    grupo.append({"simbolo": simbolo, "tf": tf, "nombre": nombre, "params": params, "entrenamiento": me,
                                  **({"simbolos": df.simbolos} if cartera else {})})
            cuenta["candidatas"] += len(grupo)
            grupo.sort(key=lambda x: -x["entrenamiento"]["sharpe"])
            candidatas.extend(grupo[: m["max_por_grupo"]])
            if progreso:
                progreso(simbolo, tf, nombre, len(grupo))
    return {
        "candidatas": candidatas,
        "por_familia": por_familia,
        "pruebas": pruebas,
        "var_sharpe_vela": float(np.var(sharpes_vela)) if sharpes_vela else 0.0,
    }
