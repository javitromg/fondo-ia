"""Carga de configuración: valores por defecto + config.yaml."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

DEFECTO = {
    "exchange": "krakenfutures",
    "simbolos": ["BTC/USD:USD", "ETH/USD:USD", "SOL/USD:USD"],
    "timeframes": ["1h", "4h"],
    "historia_dias": 1095,
    "historia_por_tf": {"1d": 3650},     # las velas diarias pesan poco: se baja todo lo que el exchange tenga
    "costes": {"comision": 0.0005, "slippage": 0.0004, "funding_8h": 0.0001},
    "dimensionado": {"vol_objetivo_anual": 0.20, "apalancamiento_max": 2.0, "ventana_vol": 72},
    "mineria": {
        "modo": "cartera",
        "timeframes": None,              # timeframes que se minan (None = todos los de `timeframes`)
        "pruebas_cartera": 150,
        "pruebas_por_estrategia": 300,
        "semilla": 42,
        "max_por_grupo": 3,
        "tramos": {"entrenamiento": 0.6, "validacion": 0.2, "reserva": 0.2},
        "filtros": {"trades_min": 40, "sharpe_min": 1.0, "pf_min": 1.2, "dd_max": 0.30},
    },
    "robustez": {
        "validacion": {"sharpe_min": 0.5, "pf_min": 1.05, "retencion_min": 0.4},
        "tramos": {"n": 6, "pct_positivos_min": 0.6},
        "montecarlo": {"simulaciones": 1000, "p5_retorno_min": 0.0, "p95_dd_max": 0.35},
        "vecindad": {"perturbacion": 0.15, "pct_rentables_min": 0.7, "retencion_mediana_min": 0.5},
        "estres_costes": {"multiplicador": 2.0},
        "reserva": {"sharpe_min": 0.5, "pf_min": 1.05},
        "dsr_min": 0.0,
        "control_ruido": {"rondas": 9},
    },
    "aprendizaje": {"cada_dias": 7},
    "rrhh": {"plantilla_objetivo": 30, "descanso_horas": 24},
    "auditoria": {"dias_min": 7, "trades_min": 3, "percentil_min": 0.05, "desvio_max": 0.03},
    "panel": {"puerto": 8765, "host": None, "sesion_dias": 30},     # host None: solo este ordenador, salvo que el entorno dé un PORT (nube)
    "vigilante": {"minutos": 10},
    "copias": {"dias": 7, "telegram": True},
    "incubadora": {
        "max_estrategias": 90,
        "capital_nocional": 10000,
        "velas_historia": 1000,
        "dias_min": 21,
        "dias_max": 90,
        "trades_min": 10,
        "sharpe_min": 0.5,
        "dd_max": 0.15,
        "por_tf": {"1d": {"trades_min": 3, "dias_max": 180}},   # un bot de velas diarias opera poco: se le da más plazo
    },
    "biblioteca": {"rondas": 99, "velas_min": 500, "cada_dias": 7},
    "analistas": {
        "activo": True,
        "cada_horas": 4,
        "titulares_max": 40,
        "fuentes": {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/", "Cointelegraph": "https://cointelegraph.com/rss",
                    "Decrypt": "https://decrypt.co/feed"},
        "modelo": "claude-haiku-4-5-20251001",     # solo se usa si existe llm_clave.txt
        "llamadas_dia_max": 20,
    },
    "riesgos": {
        "capital": 10000,
        "perdida_diaria_max": 0.02,
        "caida_max": 0.10,
        "exposicion_bruta_max": 2.0,
        "exposicion_neta_max": 1.0,
        "exposicion_simbolo_max": 0.75,
        "peso_max_estrategia": 0.25,
        "peso_max_simbolo": 0.35,
        "peso_max_apuesta": 0.5,
        "racha_min": 6,
        "pausa_bot_horas": 24,
    },
    "rutas": {"datos": "datos", "bd": "fondo.db", "informes": "informes"},
}


def _mezclar(base: dict, extra: dict) -> dict:
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mezclar(base[k], v)
        else:
            base[k] = v
    return base


def historia(cfg: dict, tf: str) -> int:
    """Días de histórico que se guardan de cada timeframe."""
    return (cfg.get("historia_por_tf") or {}).get(tf, cfg["historia_dias"])


def cargar(ruta: str | Path = "config.yaml") -> dict:
    cfg = copy.deepcopy(DEFECTO)
    ruta = Path(ruta)
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            _mezclar(cfg, yaml.safe_load(f) or {})
    # en la nube los datos viven en un volumen: FONDO_DATOS, o el que Railway monta y anuncia él mismo
    base = os.environ.get("FONDO_DATOS") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if base:
        cfg["rutas"] = {k: v if Path(v).is_absolute() else str(Path(base) / v) for k, v in cfg["rutas"].items()}
        Path(base).mkdir(parents=True, exist_ok=True)
    t = cfg["mineria"]["tramos"]
    total = t["entrenamiento"] + t["validacion"] + t["reserva"]
    if abs(total - 1.0) > 1e-9:
        raise ValueError("mineria.tramos debe sumar 1.0")
    return cfg
