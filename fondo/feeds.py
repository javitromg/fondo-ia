"""Fuentes de precios para la mesa de papel: exchange en vivo (ccxt) o repetición de un histórico."""
from __future__ import annotations

import pandas as pd

from .data import TF_MIN, _a_df


class FeedCCXT:
    """Datos públicos en vivo. No necesita claves API.

    Las velas solo se vuelven a pedir cuando puede haber cerrado una nueva, y el funding una vez
    por hora, para que un ciclo por minuto no machaque al exchange.
    """

    def __init__(self, exchange, funding_8h: float):
        self.ex, self.funding_defecto = exchange, funding_8h
        self.ahora = None
        self._velas, self._funding, self._precios = {}, {}, {}
        self._horquillas = {}

    def nuevo_ciclo(self, ahora: pd.Timestamp):
        self.ahora, self._precios = ahora, {}

    def velas(self, simbolo: str, tf: str, n: int) -> pd.DataFrame:
        paso = pd.Timedelta(minutes=TF_MIN[tf])
        clave = (simbolo, tf)
        df = self._velas.get(clave)
        if df is None or len(df) == 0 or self.ahora >= df.index[-1] + 2 * paso:      # ya ha cerrado otra vela
            df = _a_df(self.ex.fetch_ohlcv(simbolo, tf, limit=min(n + 1, 1000)))
            df = df[df.index + paso <= self.ahora]                                    # solo velas cerradas
            self._velas[clave] = df
        return df.tail(n)

    def precio(self, simbolo: str) -> float:
        if simbolo not in self._precios:
            t = self.ex.fetch_ticker(simbolo)
            self._precios[simbolo] = float(t["last"])
            compra, venta = t.get("bid"), t.get("ask")
            if compra and venta and venta >= compra > 0:
                self._horquillas[simbolo] = 2.0 * (venta - compra) / (venta + compra)
            else:
                self._horquillas.pop(simbolo, None)
        return self._precios[simbolo]

    def horquilla(self, simbolo: str) -> float | None:
        """Distancia entre la mejor compra y la mejor venta, sobre el precio medio, vista en el último precio pedido."""
        return self._horquillas.get(simbolo)

    def funding(self, simbolo: str) -> float:
        """Funding actual, expresado como tasa por 8 horas (cada exchange liquida con un intervalo distinto)."""
        previo = self._funding.get(simbolo)
        if previo and self.ahora - previo[0] < pd.Timedelta(hours=1):
            return previo[1]
        try:
            r = self.ex.fetch_funding_rate(simbolo)
            horas = pd.Timedelta(r.get("interval") or "8h").total_seconds() / 3600.0
            tasa = float(r["fundingRate"]) * 8.0 / horas
        except Exception:
            tasa = self.funding_defecto
        self._funding[simbolo] = (self.ahora, tasa)
        return tasa


class FeedReplay:
    """Reproduce un histórico vela a vela. Sirve para tests y para ensayar la incubadora sin esperar semanas."""

    def __init__(self, datos: dict, funding_8h: float):
        self.datos, self.funding_defecto = datos, funding_8h      # {(simbolo, tf): df}
        self.ahora = None

    def nuevo_ciclo(self, ahora: pd.Timestamp):
        self.ahora = ahora

    def velas(self, simbolo: str, tf: str, n: int) -> pd.DataFrame:
        df = self.datos[(simbolo, tf)]
        fin = df.index.searchsorted(self.ahora - pd.Timedelta(minutes=TF_MIN[tf]), side="right")
        return df.iloc[max(0, fin - n):fin]

    def precio(self, simbolo: str) -> float:
        tf = min((t for s, t in self.datos if s == simbolo), key=TF_MIN.get)
        df = self.datos[(simbolo, tf)]
        i = df.index.searchsorted(self.ahora, side="right") - 1
        if i < 0:
            return float(df["open"].iloc[0])
        # si `ahora` cae justo en la apertura de una vela, ese es el precio; si no, el último cierre conocido
        return float(df["open"].iloc[i]) if df.index[i] == self.ahora else float(df["close"].iloc[i])

    def funding(self, simbolo: str) -> float:
        return self.funding_defecto

    def horquilla(self, simbolo: str):
        return None
