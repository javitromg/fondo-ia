"""Tubería completa: minería -> embudo de robustez -> control de ruido."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from . import data, miner, robustness as rb


def _ronda(datos: dict, cfg: dict, progreso=None, pesos: dict | None = None) -> dict:
    r = miner.minar(datos, cfg, progreso, pesos)
    res = [rb.validar(c, datos[(c["simbolo"], c["tf"])][0], c["tf"], cfg, datos[(c["simbolo"], c["tf"])][1],
                      r["pruebas"], r["var_sharpe_vela"]) for c in r["candidatas"]]
    for x in res:
        if x["sobrevive"]:
            r["por_familia"][x["nombre"]]["supervivientes"] = r["por_familia"][x["nombre"]].get("supervivientes", 0) + 1
    return {"resultados": res, "pruebas": r["pruebas"], "embudo": rb.embudo(res, r["pruebas"]), "por_familia": r["por_familia"]}


def _placebo(df, semilla: int):
    """Serie (o cartera) con la dirección de cada vela invertida al azar."""
    if not isinstance(df, miner.Universo):
        return data.ruido(df, semilla=semilla)
    # en una cartera todas las series se invierten a la vez: siguen moviéndose juntas como en la realidad
    fechas = sorted(set().union(*[d.index for d in df.dfs.values()]))
    signos = pd.Series(np.random.default_rng(semilla).choice([-1.0, 1.0], size=len(fechas)), index=fechas)
    return miner.Universo({s: data.ruido(d, signos=signos) for s, d in df.dfs.items()}, df.fundings)


def _grupos(resultados: list[dict]) -> int:
    """Hallazgos distintos: varias supervivientes casi idénticas (misma familia, símbolo y timeframe) cuentan como uno."""
    return len({(x["simbolo"], x["tf"], x["nombre"]) for x in resultados if x["sobrevive"]})


def ejecutar(datos: dict, cfg: dict, progreso=None, aviso=print, pesos: dict | None = None) -> dict:
    """datos: {(simbolo, tf): (df o Universo, funding_vela | None)}.

    Además de minar los datos reales, repite el proceso entero sobre versiones "placebo" de esos
    mismos datos. El veredicto es un contraste estadístico: ¿en cuántas rondas de ruido salen
    tantos hallazgos como en los datos reales? Si pasa a menudo, lo encontrado es suerte.
    Con K rondas, lo mejor que se puede afirmar es p = 1/(K+1); por eso hacen falta al menos 9.
    """
    real = _ronda(datos, cfg, progreso, pesos)
    vivos, hallazgos = sum(1 for x in real["resultados"] if x["sobrevive"]), _grupos(real["resultados"])
    rondas = cfg["robustez"].get("control_ruido", {}).get("rondas", 0)
    placebo = []
    for k in range(rondas):
        if aviso:
            aviso(f"Control de ruido {k + 1}/{rondas}...")
        cfg_k = copy.deepcopy(cfg)
        cfg_k["mineria"]["semilla"] = cfg["mineria"]["semilla"] + 1000 * (k + 1)
        falsos = {clave: (_placebo(df, 7919 * (k + 1) + i), f) for i, (clave, (df, f)) in enumerate(datos.items())}
        placebo.append(_grupos(_ronda(falsos, cfg_k, None, pesos)["resultados"]))
    p_valor = (1 + sum(1 for x in placebo if x >= hallazgos)) / (rondas + 1) if rondas else None
    evidencia = bool(hallazgos > 0 and p_valor is not None and p_valor <= 0.10)
    if not rondas:
        veredicto = "Sin control de ruido: no se puede saber cuánto de esto es suerte."
    elif hallazgos == 0:
        veredicto = "No ha sobrevivido ninguna estrategia."
    elif evidencia:
        veredicto = (f"{hallazgos} hallazgos distintos en datos reales; en {rondas} rondas de ruido puro salieron {placebo} "
                     f"(p = {p_valor:.2f}). Hay señal por encima de la suerte; el siguiente filtro es la incubadora.")
    else:
        iguala = sum(1 for x in placebo if x >= hallazgos)
        motivo = (f"el ruido puro igualó o superó ese número en {iguala} de {rondas} rondas" if iguala
                  else f"con solo {rondas} rondas de ruido no se puede afirmar nada (harían falta 9)")
        veredicto = (f"Sin evidencia de ventaja: {hallazgos} hallazgos distintos en datos reales y {motivo} "
                     f"(ruido: {placebo}, p = {p_valor:.2f}). Lo encontrado es compatible con la suerte.")
    return {**real, "supervivientes": vivos, "hallazgos": hallazgos, "placebo": placebo, "p_valor": p_valor,
            "evidencia": evidencia, "veredicto": veredicto}
