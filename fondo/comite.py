"""Comité de inversión: decide quién sale de la incubadora, a quién se le quita capital y cómo se reparte.

Reglas fijas, no opinables:
- Incubadora -> fondo: tiempo mínimo, operaciones mínimas, Sharpe mínimo, en positivo y sin que Auditoría vea que en vivo no
  se parece a su simulación. Las plazas con capital son limitadas (comite.max_con_capital): entran primero los mejores, y un
  aspirante claramente mejor que el peor titular le quita el sitio.
- Incubadora -> descartada: supera la caída máxima, o agota el plazo máximo sin cumplir.
- Fondo -> incubadora: supera la caída máxima con capital asignado (se le retira el capital).
- Auditoría: si un bot rinde por debajo de lo que explica la mala suerte, se le despide (incubadora) o se le retira el capital (fondo).
- Reparto: peso inversamente proporcional a la volatilidad, con tope por estrategia, por símbolo (varios bots
  sobre la misma moneda cuentan como una sola apuesta) y por apuesta (varios bots con la misma idea, también).
  Lo que sobra se queda en caja.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import departamentos, rrhh
from .paper import Mesa, estadisticas


def reunir(mesa: Mesa, ahora: pd.Timestamp) -> dict:
    al, base, reglas = mesa.al, mesa.cfg["incubadora"], mesa.cfg.get("comite") or {}
    acta = {"promocionadas": [], "descartadas": [], "retiradas": [], "pesos": {}}
    aspirantes, titulares = [], []          # quien cumple para recibir capital y quien ya lo tiene, con sus números

    for e in al.estrategias(("incubadora", "aprobada")):
        c = al.cuenta(e["id"])
        if not c:
            continue
        inc = {**base, **(base.get("por_tf") or {}).get(e["tf"], {})}       # los bots de velas diarias tienen sus propios plazos
        s = estadisticas(al.curva(e["id"], c["alta"]), c, ahora)
        etiqueta = f"#{e['id']} {e['nombre']} {e['simbolo']} {e['tf']}"
        auditoria = (al.get(f"auditoria:{e['id']}") or {}).get("estado")
        decae = auditoria == "decaimiento"
        if c["fase"] == "incubadora":
            if decae:
                _descartar(mesa, e, c, ahora, f"Auditoría: {s['retorno']:+.1%} en {s['dias']:.0f} días, por debajo de lo que explica la mala suerte")
                acta["descartadas"].append(etiqueta)
            elif s["dd_max"] > inc["dd_max"]:
                _descartar(mesa, e, c, ahora, f"caída del {s['dd_max']:.1%} en incubadora")
                acta["descartadas"].append(etiqueta)
            elif (s["dias"] >= inc["dias_min"] and s["trades"] >= inc["trades_min"] and s["sharpe"] >= inc["sharpe_min"] and s["retorno"] > 0
                  and auditoria != "desvio"):        # si en vivo no se parece a su simulación, no se le da dinero
                aspirantes.append((s["sharpe"], e, c, s, etiqueta))
            elif s["dias"] >= inc["dias_max"]:
                _descartar(mesa, e, c, ahora, f"{s['dias']:.0f} días en incubadora sin cumplir los mínimos "
                                              f"({s['trades']} operaciones, Sharpe {s['sharpe']:.2f}, {s['retorno']:+.1%})")
                acta["descartadas"].append(etiqueta)
        elif decae or s["dd_max"] > inc["dd_max"]:
            motivo = "Auditoría lo ve por debajo de lo que explica la mala suerte" if decae else f"caída del {s['dd_max']:.1%} con capital asignado"
            _a_incubadora(mesa, e, c, ahora)
            al.set(f"auditoria:{e['id']}", None)       # empieza de cero en la incubadora
            acta["retiradas"].append(etiqueta)
            al.evento(ahora, "Comité", "retirada", f"{etiqueta}: {motivo}. Se le retira el capital y vuelve a la incubadora.")
        else:
            titulares.append((s["sharpe"], e, c, s, etiqueta, inc))

    # el capital es para los mejores: plazas limitadas, entran primero los de mejor Sharpe en vivo, y un aspirante
    # claramente mejor que el peor titular le quita el sitio
    tope, margen = reglas.get("max_con_capital"), reglas.get("margen_relevo", 0.5)
    aspirantes.sort(key=lambda x: -x[0])
    titulares.sort(key=lambda x: x[0])
    espera = 0
    for sharpe, e, c, s, etiqueta in aspirantes:
        if tope is not None and len(titulares) >= tope:
            peor = titulares[0] if titulares else None
            if peor is None or peor[3]["dias"] < peor[5]["dias_min"] or sharpe < peor[0] + margen:
                espera += 1
                continue
            _a_incubadora(mesa, peor[1], peor[2], ahora)
            al.set(f"auditoria:{peor[1]['id']}", None)
            acta["retiradas"].append(peor[4])
            al.evento(ahora, "Comité", "retirada", f"{peor[4]}: le quita el sitio {etiqueta}, que lo hace claramente mejor en vivo "
                                                    f"(Sharpe {sharpe:.2f} frente a {peor[0]:.2f}). Vuelve a la incubadora.")
            titulares.pop(0)
        _a_fondo(mesa, e, c, ahora)
        rrhh.anotar_destino(al, e["nombre"], "promocionadas")
        acta["promocionadas"].append(etiqueta)
        titulares.append((sharpe, e, c, {**s, "dias": 0.0}, etiqueta, base))        # recién llegado: no se le releva hasta que lleve su rodaje
        titulares.sort(key=lambda x: x[0])
        al.evento(ahora, "Comité", "promocion", f"{etiqueta} sale de la incubadora: {s['dias']:.0f} días, {s['trades']} operaciones, "
                                                 f"Sharpe {s['sharpe']:.2f}, {s['retorno']:+.1%}. Se le asigna capital.")
    if espera and al.get("comite:espera") != espera:
        al.evento(ahora, "Comité", "espera", f"{espera} bots cumplen los mínimos pero las {tope} plazas con capital están ocupadas por otros mejores o demasiado recientes. Siguen en la incubadora.")
    al.set("comite:espera", espera)

    acta["pesos"] = _repartir(mesa, ahora)
    resumen = (f"Comité: {len(acta['promocionadas'])} promocionadas, {len(acta['retiradas'])} retiradas, "
               f"{len(acta['descartadas'])} descartadas. {len(acta['pesos'])} estrategias con capital, "
               f"{sum(acta['pesos'].values()):.0%} invertido.")
    if acta["promocionadas"] or acta["retiradas"] or acta["descartadas"]:
        al.evento(ahora, "Comité", "acta", resumen, acta)
    al.commit()
    acta["resumen"] = resumen
    return acta


def _cerrar(mesa: Mesa, e: dict, c: dict, ahora):
    """Cierra la posición de la cuenta pagando el coste, y deja la orden apuntada para que Operaciones pueda cuadrar."""
    antes = c["pos"]
    factor = 1.0 - abs(antes) * mesa.coste
    if antes:
        mesa.al.orden(ahora, e["id"], e.get("simbolo", ""), antes, 0.0, c["precio"], c["equity"] * (1.0 - factor), "comité")
    c["equity"] *= factor
    c["nav"] *= factor
    c["pos"], c["sig"], c["tam"] = 0.0, 0.0, 0.0


def _reiniciar(c: dict, fase: str, capital: float, ahora):
    # el alta va un segundo después para que la curva de la nueva etapa no arrastre el último punto de la anterior
    c.update(fase=fase, equity=capital, nav=1.0, pico=1.0, trades=0, alta=str(pd.Timestamp(ahora) + pd.Timedelta(seconds=1)), motivo=None)


def _descartar(mesa: Mesa, e: dict, c: dict, ahora, motivo: str):
    _cerrar(mesa, e, c, ahora)
    mesa.al.guardar_cuenta(c)
    mesa.al.estado_estrategia(e["id"], "descartada", ahora)
    rrhh.anotar_destino(mesa.al, e["nombre"], "despedidas")
    mesa.al.evento(ahora, "Comité", "descarte", f"#{e['id']} {e['nombre']} {e['simbolo']} {e['tf']} descartada: {motivo}.")


def _a_fondo(mesa: Mesa, e: dict, c: dict, ahora):
    _cerrar(mesa, e, c, ahora)
    _reiniciar(c, "fondo", 0.0, ahora)      # el capital se lo da el reparto
    mesa.al.guardar_cuenta(c)
    mesa.al.estado_estrategia(e["id"], "aprobada", ahora)


def _a_incubadora(mesa: Mesa, e: dict, c: dict, ahora):
    _cerrar(mesa, e, c, ahora)
    mesa.al.set("caja", mesa.caja() + c["equity"])
    _reiniciar(c, "incubadora", mesa.cfg["incubadora"]["capital_nocional"], ahora)
    mesa.al.guardar_cuenta(c)
    mesa.al.estado_estrategia(e["id"], "incubadora", ahora)


def _repartir(mesa: Mesa, ahora) -> dict:
    al = mesa.al
    cuentas = [(e, al.cuenta(e["id"])) for e in al.estrategias(("aprobada",))]
    cuentas = [(e, c) for e, c in cuentas if c and c["fase"] == "fondo"]
    if not cuentas:
        return {}
    total = mesa.caja() + sum(c["equity"] for _, c in cuentas)
    vols = [estadisticas(al.curva(e["id"]), c, ahora)["vol_diaria"] for e, c in cuentas]
    conocidas = [v for v in vols if v > 0]
    ref = float(np.median(conocidas)) if conocidas else 1.0
    inv = np.array([1.0 / (v if v > 0 else ref) for v in vols])
    pesos = np.minimum(inv / inv.sum(), mesa.cfg["riesgos"]["peso_max_estrategia"])
    tope = mesa.cfg["riesgos"].get("peso_max_simbolo", 0.35)
    for simbolo in {e["simbolo"] for e, _ in cuentas}:      # varios bots sobre la misma moneda son una sola apuesta
        mismos = np.array([e["simbolo"] == simbolo for e, _ in cuentas])
        if pesos[mismos].sum() > tope:
            pesos[mismos] *= tope / pesos[mismos].sum()
    tope = mesa.cfg["riesgos"].get("peso_max_apuesta", 0.5)
    for grupo in {departamentos.apuesta(e) for e, _ in cuentas}:   # y muchos bots de la misma idea, una sola apuesta (lo vigila Cartera)
        mismos = np.array([departamentos.apuesta(e) == grupo for e, _ in cuentas])
        if pesos[mismos].sum() > tope:
            pesos[mismos] *= tope / pesos[mismos].sum()
    actuales = np.array([c["equity"] / total for _, c in cuentas])
    # solo se mueve capital si entra/sale alguien o si los pesos se han desviado más de 2 puntos
    if np.abs(pesos - actuales).max() > 0.02:
        caja = mesa.caja()
        for (e, c), w in zip(cuentas, pesos):
            nuevo = float(w * total)
            coste = abs(nuevo - c["equity"]) * abs(c["pos"]) * mesa.coste   # ajustar el nominal de una posición abierta cuesta
            caja += c["equity"] - nuevo - coste
            c["equity"] = nuevo
            al.guardar_cuenta(c)
        al.set("caja", caja)
        actuales = pesos
    return {f"#{e['id']}": round(float(w), 4) for (e, _), w in zip(cuentas, actuales)}
