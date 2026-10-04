"""Motor de riesgos. Es código determinista: ningún agente ni LLM puede saltárselo.

Toda orden de una estrategia con capital pasa por `revisar` antes de ejecutarse, y en cada
ciclo `vigilar` comprueba la pérdida del día y la caída desde máximos.

Exposición = nominal / capital del fondo. Largo positivo, corto negativo.
"""
from __future__ import annotations

import pandas as pd

from .store import Almacen


class MotorRiesgos:
    def __init__(self, cfg: dict, almacen: Almacen):
        self.lim = cfg["riesgos"]
        self.apal_max = cfg["dimensionado"]["apalancamiento_max"]
        self.al = almacen

    # ------------------------------------------------------------ estado
    def kill_activo(self) -> bool:
        return bool(self.al.get("kill", {}).get("activo"))

    def pausado(self, ahora: pd.Timestamp) -> bool:
        return self.al.get("pausa_dia") == str(ahora.date())

    def bloqueado(self, ahora: pd.Timestamp) -> str | None:
        if self.kill_activo():
            return "kill switch activo"
        if self.pausado(ahora):
            return "pérdida diaria máxima alcanzada"
        return None

    def activar_kill(self, ahora, motivo: str):
        self.al.set("kill", {"activo": True, "motivo": motivo, "ts": str(ahora)})
        self.al.evento(ahora, "Riesgos", "kill", f"KILL SWITCH: {motivo}. Se cierra todo y no se opera hasta reactivarlo a mano.")

    def reactivar(self, ahora, equity_fondo: float | None = None):
        self.al.set("kill", {"activo": False})
        if equity_fondo is not None:
            self.al.set("pico_fondo", equity_fondo)   # la caída se vuelve a medir desde aquí
        self.al.evento(ahora, "Riesgos", "kill", "Kill switch reactivado manualmente.")

    # ------------------------------------------------------------ control previo a cada orden
    def revisar(self, eid: int, simbolo: str, pos_actual: float, pos_objetivo: float, equity: float,
                cartera: list[dict], equity_fondo: float, ahora: pd.Timestamp) -> tuple[float, str | None]:
        """Devuelve (posición aprobada, motivo si se recortó o rechazó).

        cartera: cuentas con capital del fondo, cada una {estrategia_id, simbolo, pos, equity}.
        Reducir o cerrar siempre se aprueba; abrir o ampliar tiene que caber en todos los límites.
        """
        motivo = self.bloqueado(ahora)
        if motivo:
            return 0.0, motivo
        if equity_fondo <= 0 or equity <= 0:
            return 0.0, "sin capital"
        reduce = pos_objetivo == 0 or (pos_actual * pos_objetivo > 0 and abs(pos_objetivo) <= abs(pos_actual))
        if reduce:
            return pos_objetivo, None

        peso = equity / equity_fondo
        otras = [c for c in cartera if c["estrategia_id"] != eid]
        expo = lambda c: c["pos"] * c["equity"] / equity_fondo
        bruta = sum(abs(expo(c)) for c in otras)
        neta = sum(expo(c) for c in otras)
        neta_sim = sum(expo(c) for c in otras if c["simbolo"] == simbolo)
        signo = 1.0 if pos_objetivo > 0 else -1.0

        topes = {
            "apalancamiento máximo": self.apal_max * peso,
            "exposición bruta máxima": self.lim["exposicion_bruta_max"] - bruta,
            "exposición neta máxima": self.lim["exposicion_neta_max"] - signo * neta,
            f"exposición máxima en {simbolo}": self.lim["exposicion_simbolo_max"] - signo * neta_sim,
        }
        limite, tope = min(topes.items(), key=lambda kv: kv[1])
        pedido = abs(pos_objetivo) * peso
        if pedido <= tope + 1e-12:
            return pos_objetivo, None
        if tope <= 1e-9:
            return 0.0, f"rechazada por {limite}"
        return signo * tope / peso, f"recortada por {limite}"

    # ------------------------------------------------------------ vigilancia continua
    def vigilar(self, equity_fondo: float, ahora: pd.Timestamp) -> str | None:
        """Actualiza máximos y devuelve el motivo si hay que cerrarlo todo ahora mismo."""
        dia = str(ahora.date())
        inicio = self.al.get("inicio_dia")
        if not inicio or inicio["dia"] != dia:
            inicio = {"dia": dia, "equity": equity_fondo}
            self.al.set("inicio_dia", inicio)
        pico = max(self.al.get("pico_fondo", equity_fondo), equity_fondo)
        self.al.set("pico_fondo", pico)
        if self.kill_activo():
            return "kill switch activo"
        caida = 1.0 - equity_fondo / pico
        if caida >= self.lim["caida_max"]:
            self.activar_kill(ahora, f"caída del {caida:.1%} desde máximos (límite {self.lim['caida_max']:.0%})")
            return "kill switch activo"
        if self.pausado(ahora):
            return "pérdida diaria máxima alcanzada"
        perdida = 1.0 - equity_fondo / inicio["equity"]
        if perdida >= self.lim["perdida_diaria_max"]:
            self.al.set("pausa_dia", dia)
            self.al.evento(ahora, "Riesgos", "pausa", f"Pérdida del día {perdida:.1%} (límite {self.lim['perdida_diaria_max']:.0%}). "
                                                      "Se cierra todo y no se abre nada hasta mañana (UTC).")
            return "pérdida diaria máxima alcanzada"
        return None
