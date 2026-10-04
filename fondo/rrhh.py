"""Selección de personal: decide cuándo hace falta buscar bots nuevos y reparte el esfuerzo de búsqueda.

Dos cosas, las dos con reglas fijas:

1. Convocatorias. Si la plantilla (bots en incubadora + bots con capital) está por debajo del
   objetivo, pide al laboratorio otra ronda de búsqueda sin esperar a la semanal. Cada ronda usa
   una semilla distinta, así que explora combinaciones que no se habían probado.
2. Aprendizaje del laboratorio. Lleva la cuenta, por tipo de estrategia, de cuántas pruebas se han
   hecho, cuántas sobrevivieron al embudo, cuántas llegaron a tener capital y cuántas acabaron
   despedidas. Los tipos con mejor historial reciben más pruebas en la siguiente ronda; ninguno
   baja de la mitad, para seguir explorando. El control de ruido usa el mismo reparto, así que
   dedicar más pruebas a un tipo no lo hace pasar más fácilmente.
"""
from __future__ import annotations

import pandas as pd

from . import strategies as st
from .store import Almacen

VACIO = {"pruebas": 0, "candidatas": 0, "supervivientes": 0, "promocionadas": 0, "despedidas": 0}


def familias() -> list[str]:
    return list(st.REGISTRO) + list(st.TRANSVERSALES)


def historial(al: Almacen) -> dict:
    h = al.get("familias", {})
    return {n: {**VACIO, **h.get(n, {})} for n in familias()}


def anotar_mineria(al: Almacen, resultado: dict):
    h = historial(al)
    for n, v in (resultado.get("por_familia") or {}).items():
        if n in h:
            for k in ("pruebas", "candidatas", "supervivientes"):
                h[n][k] += v.get(k, 0)
    al.set("familias", h)


def anotar_destino(al: Almacen, nombre: str, destino: str):
    """destino: "promocionadas" o "despedidas"."""
    h = historial(al)
    if nombre in h:
        h[nombre][destino] += 1
        al.set("familias", h)


def pesos(al: Almacen) -> dict:
    """Multiplicador de pruebas por tipo de estrategia, entre 0,5 y 2,5 (1 = lo normal)."""
    h = historial(al)
    merito = {n: (1 + v["supervivientes"] + 3 * v["promocionadas"]) / (1 + v["despedidas"] + v["pruebas"] / 500) for n, v in h.items()}
    media = sum(merito.values()) / len(merito)
    return {n: round(min(2.5, max(0.5, 0.5 + 0.5 * m / media)), 2) for n, m in merito.items()}


def plantilla(al: Almacen) -> int:
    return al.contar("incubadora") + al.contar("aprobada")


def toca_convocatoria(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> str | None:
    """Motivo para lanzar una búsqueda ahora, o None si no toca."""
    no_antes = al.get("mineria_no_antes")
    if no_antes and ahora < pd.Timestamp(no_antes):      # la última ronda falló: no se reintenta hasta entonces
        return None
    ultima = al.get("ultima_mineria")
    if ultima is None:
        return "primera búsqueda"
    horas = (ahora - pd.Timestamp(ultima["ts"])).total_seconds() / 3600.0
    if horas >= cfg["aprendizaje"]["cada_dias"] * 24:
        return "toca la búsqueda periódica con los datos más recientes"
    n, objetivo = plantilla(al), cfg["rrhh"]["plantilla_objetivo"]
    if n < objetivo and horas >= cfg["rrhh"]["descanso_horas"]:
        return f"la plantilla tiene {n} de {objetivo} bots"
    return None
