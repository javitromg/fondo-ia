"""Ejecución en Kraken: copia en una cuenta de verdad la exposición del fondo. Apagada por defecto.

Tres modos, que se eligen con la variable FONDO_MODO (la pone el dueño en el servidor, no el programa):

- papel  Por defecto. Todo se simula; no se habla con ninguna cuenta.
- demo   Entorno de pruebas de Kraken Futures (demo-futures.kraken.com): plataforma de verdad, dinero ficticio.
         Sirve para comprobar que las órdenes salen, se llenan y cuadran antes de arriesgar nada.
- real   Cuenta real. Exige además FONDO_CAPITAL_MAX: el máximo de dólares de la cuenta que el fondo puede usar.

Las claves se leen de KRAKEN_API_KEY y KRAKEN_API_SECRET. Deben tener permiso para operar y NUNCA para retirar.

Qué copia: solo lo que hacen los bots CON CAPITAL (los de la incubadora siguen en papel). Para cada moneda suma la
exposición que el fondo tiene en papel, como fracción de su patrimonio, y abre en la cuenta la misma fracción del
capital disponible. Si el fondo para (kill switch, pérdida diaria), en papel se cierra todo y aquí también.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .store import Almacen

MODOS = ("papel", "demo", "real")


def modo() -> str:
    m = os.environ.get("FONDO_MODO", "papel").strip().lower()
    return m if m in MODOS else "papel"


def capital_max() -> float | None:
    try:
        v = float(os.environ.get("FONDO_CAPITAL_MAX", "").strip().replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def _claves() -> tuple[str, str] | None:
    k, s = os.environ.get("KRAKEN_API_KEY", "").strip(), os.environ.get("KRAKEN_API_SECRET", "").strip()
    return (k, s) if k and s else None


class Ejecutor:
    def __init__(self, cfg: dict, al: Almacen, exchange=None, ahora: pd.Timestamp | None = None):
        self.cfg, self.al, self.modo, self.motivo = cfg, al, modo(), None
        self.reglas = cfg.get("ejecucion_real") or {}
        self.ex, self.ultima_revision, self.ultimo_objetivo, self.fallos = None, None, None, 0
        ahora = ahora or pd.Timestamp.now(tz="UTC")
        if self.modo == "papel":
            return
        if exchange is None and _claves() is None:
            self.motivo = f"Modo {self.modo} pedido pero faltan KRAKEN_API_KEY y KRAKEN_API_SECRET: se queda en papel."
        elif self.modo == "real" and capital_max() is None:
            self.motivo = "Modo real pedido sin FONDO_CAPITAL_MAX (el tope de dólares que el fondo puede usar): se queda en papel."
        if self.motivo:
            self.modo = "papel"
            al.evento(ahora, "Ejecución", "error", self.motivo)
            al.commit()
            return
        if exchange is None:
            import ccxt
            k, s = _claves()
            exchange = ccxt.krakenfutures({"apiKey": k, "secret": s, "enableRateLimit": True})
            if self.modo == "demo":
                exchange.set_sandbox_mode(True)
        self.ex = exchange
        tope = capital_max()
        al.evento(ahora, "Ejecución", "modo", ("Modo DEMO: las órdenes del fondo se copian en el entorno de pruebas de Kraken, con dinero ficticio."
                                               if self.modo == "demo" else
                                               f"Modo REAL: las órdenes de los bots con capital se copian en tu cuenta de Kraken, usando como mucho {tope:,.0f} $.")
                  + " Solo operan los bots con capital; los de la incubadora siguen en papel.")
        al.commit()

    @property
    def activo(self) -> bool:
        return self.ex is not None

    # ------------------------------------------------------------ lo que hay en la cuenta
    def _patrimonio(self) -> float:
        b = self.ex.fetch_balance({"type": "flex"})
        flex = ((b.get("info") or {}).get("accounts") or {}).get("flex") or {}
        for k in ("portfolioValue", "marginEquity", "balanceValue"):
            if flex.get(k) is not None:
                return float(flex[k])
        return float((b.get("total") or {}).get("USD") or 0.0)

    def _posiciones(self) -> dict:
        out = {}
        for p in self.ex.fetch_positions():
            n = float(p.get("contracts") or 0.0) * float(p.get("contractSize") or 1.0)
            if n:
                out[p["symbol"]] = out.get(p["symbol"], 0.0) + (n if p.get("side") != "short" else -n)
        return out

    # ------------------------------------------------------------ lo que quiere el fondo
    @staticmethod
    def objetivo(mesa) -> dict:
        """Exposición neta del fondo en papel por moneda, como fracción de su patrimonio (+0,3 = largo por el 30 %)."""
        cuentas = mesa.cuentas_fondo()
        equity = mesa.equity_fondo()
        out = {}
        if equity <= 0:
            return out
        for c in cuentas:
            if c["pos"] and c["equity"] > 0:
                out[c["simbolo"]] = out.get(c["simbolo"], 0.0) + c["pos"] * c["equity"] / equity
        return {s: v for s, v in out.items() if abs(v) > 1e-9}

    def sincronizar(self, mesa, ahora: pd.Timestamp) -> list[str]:
        """Lleva la cuenta a la exposición del fondo. Solo manda órdenes cuando la diferencia merece la pena."""
        if not self.activo:
            return []
        obj = self.objetivo(mesa)
        cada = pd.Timedelta(minutes=self.reglas.get("revisar_cada_min", 15))
        if obj == self.ultimo_objetivo and self.ultima_revision is not None and ahora - self.ultima_revision < cada:
            return []                                       # nada ha cambiado en papel: se revisa la cuenta de vez en cuando
        hechas = []
        try:
            base = self._patrimonio()
            tope = capital_max()
            if tope is not None:
                base = min(base, tope)
            actuales = self._posiciones()
            minimo, tolerancia = self.reglas.get("min_orden_usd", 10.0), self.reglas.get("tolerancia", 0.05)
            # solo toca las monedas del fondo: lo que tengas abierto a mano en otras no lo mira (mejor aún: usa una subcuenta solo para el fondo)
            for s in sorted(set(obj) | (set(actuales) & set(self.cfg["simbolos"]))):
                precio = float(mesa.feed.precio(s))
                deseado = obj.get(s, 0.0) * base / precio
                actual = actuales.get(s, 0.0)
                dif = deseado - actual
                if abs(dif) * precio < max(minimo, tolerancia * abs(deseado) * precio):
                    continue
                cantidad = float(self.ex.amount_to_precision(s, abs(dif)))
                limite = ((self.ex.market(s).get("limits") or {}).get("amount") or {}).get("min") or 0.0
                if cantidad <= 0 or cantidad < limite:
                    continue
                reduce = actual != 0 and np.sign(deseado) in (0, np.sign(actual)) and abs(deseado) < abs(actual)
                lado = "buy" if dif > 0 else "sell"
                self.ex.create_order(s, "market", lado, cantidad, None, {"reduceOnly": True} if reduce else {})
                accion = ("cierra" if deseado == 0 else "reduce") if reduce else ("compra" if lado == "buy" else "vende")
                hechas.append(f"{s.split('/')[0]} {accion} {cantidad:g} (de {actual:+g} a {deseado:+.4g})")
            self.fallos = 0
        except Exception as e:
            self.fallos += 1
            if self.fallos in (1, 5, 30):                 # se avisa al primer fallo y si sigue fallando, no cada minuto
                self.al.evento(ahora, "Ejecución", "error", f"No se ha podido sincronizar la cuenta de Kraken ({self.modo}): {type(e).__name__}: {str(e)[:200]}")
                self.al.commit()
            return hechas
        self.ultimo_objetivo, self.ultima_revision = obj, ahora
        if hechas:
            etiqueta = "DEMO" if self.modo == "demo" else "REAL"
            self.al.evento(ahora, "Ejecución", "orden_real", f"Órdenes {etiqueta} en Kraken: " + "; ".join(hechas) + ".")
            self.al.commit()
        return hechas
