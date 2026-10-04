"""Departamentos de apoyo: lo que tiene un fondo de verdad alrededor de la mesa y que aquí faltaba.

Todos son código con reglas fijas (ningún LLM), trabajan solos y dejan constancia de lo que ven como
eventos, igual que el resto de la casa.

- Macro        Lee el estado del mercado una vez al día: tendencia de BTC, cuántas monedas acompañan,
               volatilidad y funding. Informa; no toca ninguna orden.
- Datos        Tras cada descarga comprueba que el histórico está al día, sin huecos y sin velas imposibles.
               Con datos malos, todo lo que sale del laboratorio es malo.
- Ejecución    Mide la horquilla real de cada moneda en cada ciclo y la compara con el deslizamiento que se
               supone. Si una moneda es más cara de operar de lo supuesto, la mesa le cobra lo medido.
- Cartera      Agrupa los bots por apuesta (muchos bots pueden ser la misma idea) y pone un tope de capital
               por apuesta. Mide a cuántas apuestas independientes equivale de verdad la plantilla.
- Operaciones  Cuadre diario: que la posición de cada cuenta coincide con su última orden, que nadie pasa
               de su apalancamiento, que hay precio reciente y que los límites del fondo se cumplen.
"""
from __future__ import annotations

import gzip
import math
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from . import strategies as st
from .data import TF_MIN
from .store import Almacen

# ------------------------------------------------------------------ Macro


def macro(cfg: dict) -> dict | None:
    """Estado del mercado a partir de las velas diarias guardadas. None si aún no hay bastante histórico."""
    carpeta, ex = cfg["rutas"]["datos"], cfg["exchange"]
    cierres = {}
    for s in cfg["simbolos"]:
        if data.ruta_velas(carpeta, ex, s, "1d").exists():
            c = data.cargar_velas(carpeta, ex, s, "1d")["close"]
            if len(c) >= 220:
                cierres[s] = c
    guia = next((s for s in cierres if s.startswith("BTC/")), next(iter(cierres), None))
    if guia is None:
        return None
    btc = cierres[guia]
    m200, m50, ultimo = btc.rolling(200).mean().iloc[-1], btc.rolling(50).mean().iloc[-1], btc.iloc[-1]
    tendencia = "alcista" if ultimo > m200 and m50 > m200 else "bajista" if ultimo < m200 and m50 < m200 else "lateral"
    vol = (btc.pct_change().rolling(30).std() * math.sqrt(365)).dropna()
    puesto = float((vol <= vol.iloc[-1]).mean())
    clima = "calma" if puesto < 0.33 else "tensión" if puesto > 0.8 else "normal"
    arriba = sum(1 for c in cierres.values() if c.iloc[-1] > c.rolling(200).mean().iloc[-1])
    anual = []
    for s in cierres:
        f = data.cargar_funding(carpeta, ex, s)
        if f is not None and len(f):
            reciente = f[f.index >= f.index[-1] - pd.Timedelta(days=7)]
            dias = max(1.0, (reciente.index[-1] - reciente.index[0]).total_seconds() / 86400.0)
            anual.append(float(reciente.sum()) / dias * 365.0)
    return {"guia": guia, "fecha": str(btc.index[-1].date()), "tendencia": tendencia, "clima": clima,
            "btc_vs_media": float(ultimo / m200 - 1.0), "arriba": arriba, "monedas": len(cierres),
            "vol": float(vol.iloc[-1]), "vol_puesto": puesto, "funding_anual": float(np.mean(anual)) if anual else None}


def _texto_macro(r: dict) -> str:
    lado = "por encima" if r["btc_vs_media"] >= 0 else "por debajo"
    nivel = "baja" if r["clima"] == "calma" else "alta" if r["clima"] == "tensión" else "normal"
    t = (f"Mercado {r['tendencia']}, {r['clima']}: BTC un {abs(r['btc_vs_media']):.0%} {lado} de su media de 200 días, "
         f"{r['arriba']} de {r['monedas']} monedas por encima de la suya, volatilidad del {r['vol']:.0%} anual ({nivel} para lo habitual)")
    if r["funding_anual"] is not None:
        t += f", funding medio del {r['funding_anual']:+.1%} anual"
    return t + "."


def revisar_macro(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> dict | None:
    r = macro(cfg)
    if r is None:
        return None
    previo = al.get("macro")
    cambia = previo is None or (previo["tendencia"], previo["clima"]) != (r["tendencia"], r["clima"])
    if cambia or previo.get("fecha") != r["fecha"]:
        pasa = "" if previo is None or not cambia else f" Antes: {previo['tendencia']}, {previo['clima']}."
        al.evento(ahora, "Macro", "regimen" if cambia and previo is not None else "informe", _texto_macro(r) + pasa)
    al.set("macro", {**r, "ts": str(ahora), "texto": _texto_macro(r)})
    al.commit()
    return r


# ------------------------------------------------------------------ Datos


def calidad(cfg: dict, ahora: pd.Timestamp) -> dict:
    """Repasa cada serie guardada: que exista, que esté al día, sin huecos recientes y sin velas imposibles."""
    carpeta, ex = cfg["rutas"]["datos"], cfg["exchange"]
    r = {"series": 0, "faltan": [], "atrasadas": [], "con_huecos": [], "imposibles": [], "huecos": 0}
    for s in cfg["simbolos"]:
        for tf in cfg["timeframes"]:
            nombre = f"{s.split('/')[0]} {tf}"
            if not data.ruta_velas(carpeta, ex, s, tf).exists():
                r["faltan"].append(nombre)
                continue
            df = data.cargar_velas(carpeta, ex, s, tf)
            if not len(df):
                r["faltan"].append(nombre)
                continue
            r["series"] += 1
            paso = pd.Timedelta(minutes=TF_MIN[tf])
            cerradas_sin_bajar = int((ahora - df.index[-1]) / paso) - 1      # velas ya cerradas que aún no están en disco
            if cerradas_sin_bajar >= 3 and ahora - df.index[-1] - paso >= pd.Timedelta(hours=3):
                r["atrasadas"].append(nombre)
            reciente = df[df.index >= df.index[-1] - pd.Timedelta(days=90)]
            faltan = int(round((reciente.index[-1] - reciente.index[0]) / paso)) + 1 - len(reciente)
            if faltan > 0:
                r["huecos"] += faltan
                r["con_huecos"].append(nombre)
            malas = (reciente[["open", "high", "low", "close"]] <= 0).any(axis=1) | (reciente["high"] < reciente[["open", "close"]].max(axis=1) - 1e-12) \
                | (reciente["low"] > reciente[["open", "close"]].min(axis=1) + 1e-12)
            if malas.any():
                r["imposibles"].append(nombre)
    r["limpio"] = not (r["faltan"] or r["atrasadas"] or r["con_huecos"] or r["imposibles"])
    return r


def _lista(xs: list[str], n: int = 6) -> str:
    return ", ".join(xs[:n]) + (f" y {len(xs) - n} más" if len(xs) > n else "")


def revisar_datos(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> dict:
    r = calidad(cfg, ahora)
    firma = [r["faltan"], r["atrasadas"], r["con_huecos"], r["imposibles"]]
    previo = al.get("datos")
    if previo is None or previo.get("firma") != firma:
        if r["limpio"]:
            al.evento(ahora, "Datos", "informe", f"{r['series']} series revisadas: al día, sin huecos en los últimos 90 días y sin velas imposibles.")
        else:
            partes = [f"faltan {_lista(r['faltan'])}" if r["faltan"] else "", f"van atrasadas {_lista(r['atrasadas'])}" if r["atrasadas"] else "",
                      f"{r['huecos']} velas perdidas en {_lista(r['con_huecos'])}" if r["con_huecos"] else "",
                      f"velas imposibles en {_lista(r['imposibles'])}" if r["imposibles"] else ""]
            al.evento(ahora, "Datos", "calidad", f"{r['series']} series revisadas; hay problemas: " + "; ".join(p for p in partes if p) + ".")
    al.set("datos", {**r, "firma": firma, "ts": str(ahora)})
    al.commit()
    return r


# ------------------------------------------------------------------ Ejecución


def anotar_horquillas(al: Almacen, medidas: dict):
    """Acumula en la base las horquillas vistas por la mesa ({simbolo: [n, suma]}), para el informe diario."""
    if not medidas:
        return
    acum = al.get("ejecucion:medidas", {})
    for s, (n, suma) in medidas.items():
        a = acum.get(s, [0, 0.0])
        acum[s] = [a[0] + n, a[1] + suma]
    al.set("ejecucion:medidas", acum)


def revisar_ejecucion(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> dict | None:
    """Compara media horquilla (lo que cuesta de verdad cruzar el mercado) con el deslizamiento supuesto."""
    acum = al.get("ejecucion:medidas", {})
    medio = {s: suma / n / 2.0 for s, (n, suma) in acum.items() if n >= 30}
    if not medio:
        return None
    supuesto = cfg["costes"]["slippage"]
    caras = sorted(((s, v) for s, v in medio.items() if v > supuesto), key=lambda x: -x[1])
    r = {"ts": str(ahora), "supuesto": supuesto, "medio": medio, "media": float(np.mean(list(medio.values()))),
         "caras": [s for s, _ in caras], "muestras": int(sum(n for n, _ in acum.values()))}
    texto = (f"Horquilla medida en {len(medio)} monedas: cruzar el mercado cuesta de media un {r['media']:.3%} por lado, "
             f"frente al {supuesto:.3%} de deslizamiento supuesto. ")
    nombres = [s.split("/")[0] + f" ({v:.3%})" for s, v in caras]
    texto += ("Ninguna moneda sale más cara de lo supuesto." if not caras else
              f"Más caras de lo supuesto: {_lista(nombres)}. A esas se les cobra lo medido, en vivo y en las simulaciones.")
    # media suavizada de varios días: es la que usan la mesa, la minería, la biblioteca y la auditoría
    media = al.get("ejecucion:media", {})
    for s, v in medio.items():
        media[s] = v if s not in media else 0.7 * media[s] + 0.3 * v
    al.set("ejecucion:media", media)
    previo = al.get("ejecucion")
    al.evento(ahora, "Ejecución", "costes" if previo is None or previo.get("caras") != r["caras"] else "informe", texto)
    al.set("ejecucion", {**r, "texto": texto})
    al.set("ejecucion:medidas", {})          # cada día se mide de nuevo: la liquidez cambia
    al.commit()
    return r


def deslizamiento(al: Almacen, cfg: dict) -> dict:
    """Deslizamiento por lado de cada moneda: el supuesto o, si es mayor, el medido (media suavizada de varios días)."""
    supuesto = cfg["costes"]["slippage"]
    return {s: max(supuesto, v) for s, v in (al.get("ejecucion:media") or {}).items()}


def costes_con_medidas(al: Almacen, cfg: dict) -> dict:
    """Los costes de config más lo que Ejecución ha medido por moneda. Así una simulación paga lo mismo que pagaría la mesa."""
    return {**cfg["costes"], "por_simbolo": deslizamiento(al, cfg)}


# ------------------------------------------------------------------ Cartera

TENDENCIA = "tendencia (solo largos)"


def apuesta(e: dict) -> str:
    """A qué apuesta pertenece un bot. Los modelos publicados de tendencia son la misma idea con otra regla:
    cuando el mercado sube están todos dentro y cuando cae, todos fuera."""
    return TENDENCIA if e["nombre"] in st.PUBLICADAS else e["nombre"].replace("_", " ")


def _independientes(al: Almacen, bots: list[tuple[dict, float]]) -> float | None:
    """Número de apuestas independientes a las que equivale el grupo, según cómo se han movido juntos sus resultados."""
    series, pesos = [], []
    for e, w in bots:
        c = al.cuenta(e["id"])
        curva = al.curva(e["id"], c["alta"]) if c else pd.Series(dtype=float)
        diario = curva.resample("1D").last().dropna().pct_change().dropna() if len(curva) > 2 else curva
        if len(diario) >= 15 and diario.std() > 0:
            series.append(diario)
            pesos.append(w)
    if len(series) < 2:
        return None
    tabla = pd.concat(series, axis=1).dropna()
    if len(tabla) < 15:
        return None
    corr = np.nan_to_num(tabla.corr().to_numpy(), nan=0.0)
    w = np.array(pesos) / sum(pesos)
    return float(1.0 / max(w @ corr @ w, 1e-9))


def revisar_cartera(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> dict:
    tope = cfg["riesgos"].get("peso_max_apuesta", 0.5)
    fondo, total = [], 0.0
    for e in al.estrategias(("aprobada",)):
        c = al.cuenta(e["id"])
        if c and c["fase"] == "fondo":
            fondo.append((e, c["equity"]))
            total += c["equity"]
    incub = [(e, 1.0) for e in al.estrategias(("incubadora",))]
    grupo = fondo if fondo else incub
    reparto = {}
    for e, w in grupo:
        reparto[apuesta(e)] = reparto.get(apuesta(e), 0.0) + w
    suma = sum(reparto.values()) or 1.0
    orden = sorted(reparto.items(), key=lambda kv: -kv[1])
    indep = _independientes(al, grupo)
    r = {"ts": str(ahora), "ambito": "fondo" if fondo else "incubadora", "bots": len(grupo), "tope": tope,
         "apuestas": [{"nombre": k, "peso": v / suma, "bots": sum(1 for e, _ in grupo if apuesta(e) == k)} for k, v in orden],
         "independientes": indep}
    if not grupo:
        texto = "Todavía no hay bots que agrupar."
    else:
        lista = _lista([f"{a['nombre']} ({a['bots']} {'bot' if a['bots'] == 1 else 'bots'}, {a['peso']:.0%})" for a in r["apuestas"]], 4)
        donde = "Con capital" if fondo else "En incubadora"
        cuantas = "una sola apuesta" if len(reparto) == 1 else f"{len(reparto)} apuestas distintas"
        texto = f"{donde}: {len(grupo)} bots en {cuantas}: {lista}."
        if indep is not None:
            texto += f" Por cómo se mueven juntos, equivalen a {indep:.1f} apuestas independientes."
        texto += f" Ninguna apuesta puede llevarse más del {tope:.0%} del capital."
    r["texto"] = texto
    previo = al.get("cartera")
    firma = [r["ambito"], [[a["nombre"], a["bots"]] for a in r["apuestas"]]]      # con listas: así vuelve igual al leerla de la base
    if previo is None or previo.get("firma") != firma:
        al.evento(ahora, "Cartera", "informe", texto)
    al.set("cartera", {**r, "firma": firma})
    al.commit()
    return r


# ------------------------------------------------------------------ Operaciones


def revisar_operaciones(al: Almacen, cfg: dict, ahora: pd.Timestamp, en_marcha: bool = True) -> dict:
    """Cuadre: lo que dicen las cuentas tiene que coincidir con lo que dicen las órdenes y con los límites."""
    lim, apal = cfg["riesgos"], cfg["dimensionado"]["apalancamiento_max"]
    incidencias, cuentas, sin_precio = [], 0, []
    caja = al.get("caja", lim["capital"])
    fondo = []
    for e in al.estrategias(("incubadora", "aprobada")):
        c = al.cuenta(e["id"])
        if not c:
            continue
        cuentas += 1
        etiqueta = f"#{e['id']} {e['simbolo'].split('/')[0]}"
        ultima = al.db.execute("SELECT pos_despues FROM ordenes WHERE estrategia_id=? ORDER BY id DESC LIMIT 1", (e["id"],)).fetchone()
        if ultima is not None and abs(ultima["pos_despues"] - c["pos"]) > 1e-6:
            incidencias.append(f"{etiqueta}: la cuenta dice {c['pos']:+.2f}x y su última orden {ultima['pos_despues']:+.2f}x")
        elif ultima is None and abs(c["pos"]) > 1e-9:
            incidencias.append(f"{etiqueta}: tiene posición {c['pos']:+.2f}x sin ninguna orden registrada")
        if abs(c["pos"]) > apal + 1e-6:
            incidencias.append(f"{etiqueta}: posición {c['pos']:+.2f}x por encima del apalancamiento máximo {apal:.1f}x")
        if not (math.isfinite(c["nav"]) and math.isfinite(c["equity"]) and c["nav"] > 0 and c["equity"] >= 0):
            incidencias.append(f"{etiqueta}: cuenta con valores imposibles (nav {c['nav']}, capital {c['equity']})")
        if (e["estado"] == "aprobada") != (c["fase"] == "fondo"):
            incidencias.append(f"{etiqueta}: figura como {e['estado']} pero su cuenta está en fase {c['fase']}")
        if en_marcha and c["ts_marca"] and ahora - pd.Timestamp(c["ts_marca"]) > pd.Timedelta(minutes=30):
            sin_precio.append(etiqueta)
        if c["fase"] == "fondo":
            fondo.append((e, c))
    equity = caja + sum(c["equity"] for _, c in fondo)
    if caja < -0.01:
        incidencias.append(f"la caja está en negativo ({caja:,.2f})")
    if equity > 0 and fondo:
        expo = {}
        for e, c in fondo:
            expo[e["simbolo"]] = expo.get(e["simbolo"], 0.0) + c["pos"] * c["equity"] / equity
        bruta, neta = sum(abs(v) for v in expo.values()), abs(sum(expo.values()))
        margen = 1.05          # las posiciones se mueven con el precio entre una orden y la siguiente
        if bruta > lim["exposicion_bruta_max"] * margen:
            incidencias.append(f"exposición bruta {bruta:.2f}x por encima del límite {lim['exposicion_bruta_max']:.2f}x")
        if neta > lim["exposicion_neta_max"] * margen:
            incidencias.append(f"exposición neta {neta:.2f}x por encima del límite {lim['exposicion_neta_max']:.2f}x")
        for s, v in expo.items():
            if abs(v) > lim["exposicion_simbolo_max"] * margen:
                incidencias.append(f"{s.split('/')[0]}: exposición {abs(v):.2f}x por encima del límite por moneda {lim['exposicion_simbolo_max']:.2f}x")
    if sin_precio:
        incidencias.append(f"{len(sin_precio)} cuentas llevan más de 30 minutos sin precio: {_lista(sin_precio)}")
    ordenes = al.db.execute("SELECT count(*) FROM ordenes").fetchone()[0]
    r = {"ts": str(ahora), "cuentas": cuentas, "ordenes": ordenes, "incidencias": incidencias}
    previo = al.get("operaciones")
    if incidencias:
        if previo is None or previo.get("incidencias") != incidencias:
            al.evento(ahora, "Operaciones", "descuadre", f"Cuadre con {len(incidencias)} incidencias: " + "; ".join(incidencias[:5])
                      + (f"; y {len(incidencias) - 5} más" if len(incidencias) > 5 else "") + ".")
    elif previo is None or previo.get("incidencias") or previo["ts"][:10] != str(ahora)[:10]:
        al.evento(ahora, "Operaciones", "cuadre", f"Cuadre: {cuentas} cuentas y {ordenes} órdenes revisadas. Posiciones, capital y límites coinciden.")
    r["texto"] = "Todo cuadra." if not incidencias else f"{len(incidencias)} incidencias: " + "; ".join(incidencias[:3])
    al.set("operaciones", r)
    al.commit()
    return r


def copia(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> Path | None:
    """Copia diaria de la base (en caliente, sin parar nada) junto a ella, en copias/. Se guardan las últimas `copias.dias`.
    Los lunes deja además una comprimida para mandarla por Telegram: es la única copia que vive fuera del servidor."""
    bd = Path(cfg["rutas"]["bd"])
    if str(bd) == ":memory:" or not bd.exists():
        return None
    carpeta = bd.resolve().parent / "copias"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"fondo_{ahora:%Y%m%d}.db"
    al.commit()
    con = sqlite3.connect(str(destino))
    try:
        al.db.backup(con)
    finally:
        con.close()
    viejas = sorted(carpeta.glob("fondo_*.db"))[: -max(1, cfg["copias"]["dias"])]
    for v in viejas:
        v.unlink(missing_ok=True)
    mb = destino.stat().st_size / 1e6
    al.evento(ahora, "Operaciones", "copia", f"Copia de seguridad de hoy hecha ({mb:.1f} MB). Se guardan las {cfg['copias']['dias']} últimas.")
    if cfg["copias"].get("telegram") and ahora.dayofweek == 0:
        for v in carpeta.glob("fondo_*.db.gz"):
            v.unlink(missing_ok=True)
        gz = destino.with_suffix(".db.gz")
        with open(destino, "rb") as origen, gzip.open(gz, "wb") as salida:
            shutil.copyfileobj(origen, salida)
        if gz.stat().st_size < 45e6:              # Telegram no admite más de 50 MB por archivo
            al.set("copia:enviar", str(gz))
    al.commit()
    return destino


# ------------------------------------------------------------------ Dirección: informe semanal

def _pct(x: float) -> str:
    return f"{x * 100:+.2f} %".replace(".", ",")


def informe_semanal(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> str | None:
    """Los lunes, resumen de la semana: cómo va el fondo, quién destaca, qué ha decidido el comité y cuánto ha gastado el modelo."""
    if ahora.dayofweek != 0 or al.get("semanal") == str(ahora.date()):
        return None
    desde = ahora - pd.Timedelta(days=7)
    capital = cfg["riesgos"]["capital"]
    curva = al.curva(0, desde)
    caja = al.get("caja", capital)
    activos = al.estrategias(("incubadora", "aprobada"))
    cuentas = {e["id"]: c for e in activos if (c := al.cuenta(e["id"]))}
    equity = caja + sum(c["equity"] for c in cuentas.values() if c["fase"] == "fondo")
    semana = equity / curva.iloc[0] - 1.0 if len(curva) and curva.iloc[0] > 0 else 0.0
    lineas = [f"Informe semanal. Patrimonio {equity:,.2f} $: {_pct(semana)} en la semana, {_pct(equity / capital - 1.0)} desde el inicio.",
              f"Plantilla: {al.contar('aprobada')} con capital y {al.contar('incubadora')} en incubadora."]
    tipos = dict(al.db.execute("SELECT tipo, count(*) FROM eventos WHERE ts >= ? GROUP BY tipo", (str(desde),)).fetchall())
    altas = al.db.execute("SELECT count(*) FROM estrategias WHERE creado >= ?", (str(desde),)).fetchone()[0]
    lineas.append(f"Esta semana: {altas} contratados, {tipos.get('promocion', 0)} con capital nuevo, {tipos.get('retirada', 0)} sin capital, {tipos.get('descarte', 0)} despedidos.")
    filas = []
    for e in activos:
        c = cuentas.get(e["id"])
        nav = al.curva(e["id"], max(str(desde), c["alta"])) if c else []
        if len(nav) >= 2 and nav.iloc[0] > 0:
            filas.append((nav.iloc[-1] / nav.iloc[0] - 1.0, f"n.º {e['id']} {e['nombre'].replace('_', ' ')} {e['simbolo'].split('/')[0]}"))
    filas.sort(key=lambda x: -x[0])
    if filas:
        lineas.append("Mejores: " + "; ".join(f"{n} {_pct(r)}" for r, n in filas[:3]) + ".")
        if len(filas) > 3:
            lineas.append("Peores: " + "; ".join(f"{n} {_pct(r)}" for r, n in filas[-3:][::-1]) + ".")
    problemas = {k: tipos.get(k, 0) for k in ("error", "descuadre", "caida", "calidad", "modo_seguro")}
    lineas.append("Incidencias: " + (", ".join(f"{v} de {k.replace('_', ' ')}" for k, v in problemas.items() if v) or "ninguna") + ".")
    total, antes = al.get("llm:total") or {}, al.get("llm:semana") or {}
    if total:
        lineas.append(f"Modelo de lenguaje: {total.get('llamadas', 0) - antes.get('llamadas', 0)} consultas, "
                      f"{total.get('entrada', 0) - antes.get('entrada', 0):,} tokens de entrada y {total.get('salida', 0) - antes.get('salida', 0):,} de salida.".replace(",", "."))
        al.set("llm:semana", total)
    texto = "\n".join(lineas)
    al.evento(ahora, "Dirección", "semanal", texto)
    al.set("semanal", str(ahora.date()))
    al.commit()
    return texto


# ------------------------------------------------------------------ todos a la vez


def ronda(al: Almacen, cfg: dict, ahora: pd.Timestamp, cierre: bool = True):
    """Pasa por todos los departamentos de apoyo. Si uno falla, lo dice y los demás siguen."""
    tareas = [("Cartera", revisar_cartera), ("Operaciones", revisar_operaciones), ("Macro", revisar_macro)]
    if cierre:
        tareas[2:2] = [("Ejecución", revisar_ejecucion), ("Operaciones", copia)]
        tareas.append(("Dirección", informe_semanal))
    for nombre, fn in tareas:
        try:
            if fn is revisar_operaciones:
                fn(al, cfg, ahora, en_marcha=cierre)     # recién arrancado, los precios guardados pueden ser de ayer
            else:
                fn(al, cfg, ahora)
        except Exception as e:
            al.db.rollback()
            al.evento(ahora, nombre, "error", f"No ha podido hacer su revisión: {type(e).__name__}: {e}")
            al.commit()


def estado(al: Almacen) -> dict:
    return {k: al.get(k) for k in ("macro", "datos", "ejecucion", "cartera", "operaciones")}
