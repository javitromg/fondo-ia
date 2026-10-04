"""Mesa de papel: ejecuta en simulado, con precios en vivo, las estrategias en incubadora y las aprobadas.

Sigue las mismas reglas que el backtester (señal al cierre, ejecución en la apertura siguiente,
tamaño fijado al abrir, comisión + slippage + funding), para que lo visto en la incubadora sea
comparable con lo visto en el histórico.

- Incubadora: cada estrategia opera un capital ficticio aislado. No cuenta para el fondo.
- Fondo: las aprobadas operan el capital que les asigna el comité y toda orden pasa por Riesgos.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import departamentos
from . import strategies as st
from .backtest import tamano
from .risk import MotorRiesgos
from .store import FONDO, Almacen


def _precio(x: float) -> str:
    return f"{x:,.2f}" if x >= 100 else f"{x:.4g}"


class Mesa:
    def __init__(self, cfg: dict, almacen: Almacen, feed):
        self.cfg, self.al, self.feed = cfg, almacen, feed
        self.riesgos = MotorRiesgos(cfg, almacen)
        self.coste = cfg["costes"]["comision"] + cfg["costes"]["slippage"]
        self.medidas, self._desliz = {}, {}       # horquillas vistas desde el último apunte; deslizamiento medido por moneda

    def coste_de(self, simbolo: str) -> float:
        """Coste por lado de operar esa moneda: comisión más el deslizamiento supuesto o, si Ejecución midió más, el medido."""
        return self.cfg["costes"]["comision"] + self._desliz.get(simbolo, self.cfg["costes"]["slippage"])

    # ------------------------------------------------------------ fondo
    def caja(self) -> float:
        return self.al.get("caja", self.cfg["riesgos"]["capital"])

    def cuentas_fondo(self) -> list[dict]:
        out = []
        for e in self.al.estrategias(("aprobada",)):
            c = self.al.cuenta(e["id"])
            if c and c["fase"] == "fondo":
                out.append({**c, "simbolo": e["simbolo"]})
        return out

    def equity_fondo(self) -> float:
        return self.caja() + sum(c["equity"] for c in self.cuentas_fondo())

    # ------------------------------------------------------------ ciclo
    def ciclo(self, ahora: pd.Timestamp) -> dict:
        """Una pasada: marca a mercado, vigila riesgos, calcula señales y ejecuta lo que toque."""
        self.feed.nuevo_ciclo(ahora)
        ests = self.al.estrategias(("incubadora", "aprobada"))
        self._desliz = departamentos.deslizamiento(self.al, self.cfg)
        cuentas, sin_precio, fallos = {}, set(), []
        for e in ests:
            c = self.al.cuenta(e["id"]) or self.al.nueva_cuenta(e["id"], "incubadora", self.cfg["incubadora"]["capital_nocional"], ahora)
            try:
                self._marcar(c, e["simbolo"], ahora)
            except Exception as err:       # sin precio de esa moneda en este ciclo: se queda como estaba
                sin_precio.add(e["id"])
                fallos.append(f"#{e['id']} {e['simbolo']}: {type(err).__name__}: {err}")
            cuentas[e["id"]] = c

        medir = getattr(self.feed, "horquilla", None)
        for simbolo in {e["simbolo"] for e in ests if e["id"] not in sin_precio}:      # Ejecución: la horquilla real, una vez por moneda
            h = medir(simbolo) if medir else None
            if h is not None:
                m = self.medidas.setdefault(simbolo, [0, 0.0])
                m[0], m[1] = m[0] + 1, m[1] + h

        del_fondo = lambda: [{**c, "simbolo": e["simbolo"]} for e in ests if (c := cuentas[e["id"]])["fase"] == "fondo"]
        equity_fondo = self.caja() + sum(c["equity"] for c in del_fondo())
        bloqueo = self.riesgos.vigilar(equity_fondo, ahora)

        ordenes, memo = 0, {}
        for e in ests:
            c = cuentas[e["id"]]
            if e["id"] in sin_precio:
                continue
            try:
                ordenes += self._operar(e, c, ahora, del_fondo, equity_fondo, bloqueo, memo)
            except Exception as err:       # una moneda que falla no debe parar a las demás
                fallos.append(f"#{e['id']} {e['simbolo']}: {type(err).__name__}: {err}")
            self.al.guardar_cuenta(c)
        if fallos and self.al.get("ultimo_fallo") != fallos[0]:
            self.al.evento(ahora, "Sistema", "error", f"{len(fallos)} estrategias no han podido operar en este ciclo. Primera: {fallos[0]}")
            self.al.set("ultimo_fallo", fallos[0])

        equity_fondo = self.caja() + sum(c["equity"] for c in del_fondo())
        previo = self.al.get("ts_curva_fondo")
        if previo is None or ahora - pd.Timestamp(previo) >= pd.Timedelta(minutes=15):
            self.al.apuntar_equity(ahora, FONDO, equity_fondo)
            self.al.set("ts_curva_fondo", str(ahora))
            departamentos.anotar_horquillas(self.al, self.medidas)
            self.medidas = {}
        self.al.commit()
        return {"estrategias": len(ests), "ordenes": ordenes, "equity_fondo": equity_fondo, "bloqueo": bloqueo}

    def _senal(self, e: dict, velas: pd.DataFrame, memo: dict) -> float:
        """Señal de la última vela cerrada. Las transversales necesitan las velas de todo su universo."""
        if e["nombre"] not in st.TRANSVERSALES:
            return float(st.senal(e["nombre"], velas, e["params"])[-1])
        universo = e["metricas"].get("universo") or [e["simbolo"]]
        clave = (e["nombre"], e["tf"], json.dumps(e["params"], sort_keys=True), tuple(universo))
        if clave not in memo:
            n = self.cfg["incubadora"]["velas_historia"]
            dfs = {s: (velas if s == e["simbolo"] else self.feed.velas(s, e["tf"], n)) for s in universo}
            memo[clave] = st.senal_transversal(e["nombre"], {s: d for s, d in dfs.items() if len(d)}, e["params"])
        return float(memo[clave][e["simbolo"]][-1])

    def _operar(self, e: dict, c: dict, ahora: pd.Timestamp, del_fondo, equity_fondo: float, bloqueo, memo: dict) -> int:
        velas = self.feed.velas(e["simbolo"], e["tf"], self.cfg["incubadora"]["velas_historia"])
        if len(velas) == 0:
            return 0
        ultima = str(velas.index[-1])
        nueva = c["ultima_vela"] is None or ultima > c["ultima_vela"]
        if nueva:
            sig = self._senal(e, velas, memo)
            if sig != c["sig"]:
                c["sig"], c["tam"] = sig, float(tamano(velas, e["tf"], self.cfg["dimensionado"])[-1])
            c["ultima_vela"] = ultima
        objetivo, motivo = c["sig"] * c["tam"], None
        if c.get("pausa_hasta"):                 # modo seguro: fuera del mercado hasta que pase la pausa
            if ahora < pd.Timestamp(c["pausa_hasta"]):
                objetivo = 0.0
            else:
                c["pausa_hasta"] = None
        if c["fase"] == "fondo":
            objetivo, motivo = self.riesgos.revisar(e["id"], e["simbolo"], c["pos"], objetivo, c["equity"], del_fondo(), equity_fondo, ahora)
            if motivo and motivo != c["motivo"]:
                self.al.evento(ahora, "Riesgos", "orden", f"#{e['id']} {e['nombre']} {e['simbolo']}: {motivo}.")
            c["motivo"] = motivo
        forzar = c["fase"] == "fondo" and bloqueo is not None
        hecho = 0
        if abs(objetivo - c["pos"]) > 1e-9 and (nueva or forzar):
            self._ejecutar(e, c, objetivo, ahora, motivo)
            hecho = 1
        if nueva:
            self.al.apuntar_equity(ahora, e["id"], c["nav"])
        return hecho

    # ------------------------------------------------------------ internos
    def _marcar(self, c: dict, simbolo: str, ahora: pd.Timestamp):
        precio = self.feed.precio(simbolo)
        if c["precio"] and c["pos"] != 0:
            horas = (ahora - pd.Timestamp(c["ts_marca"])).total_seconds() / 3600.0
            factor = 1.0 + c["pos"] * (precio / c["precio"] - 1.0) - c["pos"] * self.feed.funding(simbolo) * horas / 8.0
            factor = max(factor, 0.0)
            c["equity"] *= factor
            c["nav"] *= factor
        c["precio"], c["ts_marca"], c["pico"] = precio, str(ahora), max(c["pico"], c["nav"])

    def _ejecutar(self, e: dict, c: dict, objetivo: float, ahora: pd.Timestamp, motivo: str | None):
        antes, coste_lado = c["pos"], self.coste_de(e["simbolo"])
        gira = antes != 0 and objetivo != 0 and np.sign(antes) != np.sign(objetivo)
        cierra = antes != 0 and (objetivo == 0 or gira)
        if cierra and c.get("nav_entrada"):
            # resultado de la operación que se cierra, con su coste de salida
            resultado = c["nav"] * (1.0 - abs(antes) * coste_lado) / c["nav_entrada"] - 1.0
            c["racha"] = (c.get("racha") or 0) + 1 if resultado < 0 else 0
            limite = self._racha_limite(e["id"])
            if limite and c["racha"] >= limite:
                horas = self.cfg["riesgos"]["pausa_bot_horas"]
                c["pausa_hasta"] = str(ahora + pd.Timedelta(hours=horas))
                self.al.evento(ahora, "Riesgos", "modo_seguro", f"#{e['id']} {e['nombre']} {e['simbolo']} {e['tf']}: {c['racha']} operaciones perdedoras seguidas, "
                               f"más que nunca en su histórico. Modo seguro: fuera del mercado {horas} horas.")
                c["racha"], objetivo, gira = 0, 0.0, False
        factor = 1.0 - abs(objetivo - antes) * coste_lado
        coste = c["equity"] * (1.0 - factor)
        if objetivo != 0 and (antes == 0 or gira):
            c["trades"] += 1
            c["nav_entrada"] = c["nav"]          # antes del coste: la comisión de entrada cuenta en el resultado de la operación
        c["equity"] *= factor
        c["nav"] *= factor
        c["pos"] = objetivo
        self.al.orden(ahora, e["id"], e["simbolo"], antes, objetivo, c["precio"], coste, motivo)
        lado = "largo" if objetivo > 0 else "corto"
        if objetivo == 0:
            accion = "cierra posición"
        elif antes == 0:
            accion = f"abre {lado} {abs(objetivo):.2f}x"
        elif gira:
            accion = f"gira a {lado} {abs(objetivo):.2f}x"
        else:
            accion = f"ajusta {lado} a {abs(objetivo):.2f}x"
        origen = "Mesa" if c["fase"] == "fondo" else "Incubadora"
        self.al.evento(ahora, origen, "orden", f"#{e['id']} {e['nombre']} {e['simbolo']} {e['tf']}: {accion} a {_precio(c['precio'])}" + (f" ({motivo})" if motivo else ""))

    def _racha_limite(self, eid: int) -> int | None:
        """Pérdidas seguidas que disparan el modo seguro: dos más que la peor racha de su histórico (la calcula Auditoría)."""
        peor = self.al.get(f"racha:{eid}")
        return None if peor is None else max(self.cfg["riesgos"]["racha_min"], int(peor) + 2)


def estadisticas(curva: pd.Series, c: dict, ahora: pd.Timestamp) -> dict:
    """Rendimiento de una cuenta desde su alta, a partir de su curva de nav."""
    dias = (ahora - pd.Timestamp(c["alta"])).total_seconds() / 86400.0
    diario = curva.resample("1D").last().dropna().pct_change().dropna() if len(curva) > 1 else pd.Series(dtype=float)
    sd = diario.std(ddof=1) if len(diario) > 2 else 0.0
    return {
        "dias": dias,
        "trades": c["trades"],
        "retorno": c["nav"] - 1.0,
        "dd": 1.0 - c["nav"] / c["pico"] if c["pico"] > 0 else 0.0,
        "dd_max": float((1.0 - curva / curva.cummax()).max()) if len(curva) else 0.0,
        "sharpe": float(diario.mean() / sd * np.sqrt(365)) if sd and sd > 0 else 0.0,
        "vol_diaria": float(sd) if sd else 0.0,
    }
