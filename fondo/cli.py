"""Comandos:  python -m fondo <comando>

  demo        Prueba completa con datos sintéticos (sin internet): minería, embudo, incubadora y comité.
  descargar   Baja o actualiza el histórico de velas y funding del exchange.
  minar       Mina estrategias, pasa el embudo de robustez y manda las supervivientes a la incubadora.
  auto        TODO EN UNO, 24/7: datos al día, mesa de papel cada minuto, comité diario,
              minería semanal con lo último y panel en vivo. Es el comando que se deja encendido.
  panel       Solo el panel web en vivo (http://localhost:8765).
  biblioteca  Compara los modelos publicados con el histórico y contrata los que mejoran a comprar y mantener.
  incubar-ultima  Incuba en papel las supervivientes de la última minería aunque no hubiera evidencia (quedan marcadas).
  incubar     Solo la mesa de papel en vivo: incubadora + fondo simulado, con Riesgos y comité diario.
  comite      Reúne al comité ahora (promociones, descartes y reparto de capital).
  estado      Resumen del fondo, la incubadora y los últimos eventos.
  kill        Activa el kill switch (o lo reactiva con --reactivar).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

from . import comite as comite_mod
from . import auto as auto_mod
from . import biblioteca, config, data, departamentos, miner, panel, pipeline, report, rrhh
from .feeds import FeedCCXT, FeedReplay
from .paper import Mesa, estadisticas
from .store import FONDO, Almacen


def _ahora() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").floor("s")


def _cargar_datos(cfg: dict) -> dict:
    """Series para minar según mineria.modo: "cartera" (mismos parámetros en todos los símbolos),
    "individual" (cada símbolo por separado) o "ambos"."""
    modo = cfg["mineria"].get("modo", "cartera")
    sueltas, por_tf, faltan = {}, {}, []
    for s in cfg["simbolos"]:
        funding = data.cargar_funding(cfg["rutas"]["datos"], cfg["exchange"], s)
        for tf in cfg["mineria"].get("timeframes") or cfg["timeframes"]:
            if not data.ruta_velas(cfg["rutas"]["datos"], cfg["exchange"], s, tf).exists():
                faltan.append(f"{s} {tf}")
                continue
            df = data.cargar_velas(cfg["rutas"]["datos"], cfg["exchange"], s, tf, config.historia(cfg, tf))
            if len(df) < 2000:
                print(f"{s} {tf}: solo {len(df)} velas, no se mina (hace falta más histórico).")
                continue
            f = data.funding_por_vela(df.index, tf, funding, cfg["costes"]["funding_8h"])
            sueltas[(s, tf)] = (df, f)
            por_tf.setdefault(tf, {})[s] = (df, f)
    if faltan:
        print("Sin datos para:", ", ".join(faltan), "-> ejecuta antes: python -m fondo descargar")
    datos = {}
    if modo in ("cartera", "ambos"):
        for tf, d in por_tf.items():
            if len(d) >= 4:
                datos[(miner.CARTERA, tf)] = (miner.Universo({s: v[0] for s, v in d.items()}, {s: v[1] for s, v in d.items()}), None)
            else:
                print(f"Cartera {tf}: solo {len(d)} símbolos con datos, hacen falta al menos 4.")
    if modo in ("individual", "ambos"):
        datos.update(sueltas)
    return datos


def _registrar(al: Almacen, resultado: dict, ahora, tope: int | None = None, sin_evidencia: bool = False) -> int:
    """Manda las supervivientes a la incubadora, las mejores primero, sin pasar del tope de plazas.

    Una cartera superviviente entra como una estrategia por símbolo, todas con los mismos parámetros.
    sin_evidencia=True las marca como "a prueba": la minería no las distinguió de la suerte y solo
    están ahí para ver cómo se comportan en papel.
    """
    nuevas, vistos = 0, set()
    libres = None if tope is None else max(0, tope - al.contar("incubadora"))
    vivas = sorted((x for x in resultado["resultados"] if x["sobrevive"]), key=lambda x: -x["reserva"]["sharpe"])
    marca = " a prueba, sin evidencia estadística" if sin_evidencia else ""
    for x in vivas:
        m = {k: x[k] for k in ("entrenamiento", "validacion", "reserva", "dsr")}
        m["sin_evidencia"] = sin_evidencia
        if x["simbolo"] == miner.CARTERA:
            if (x["tf"], x["nombre"]) in vistos:        # de varias carteras casi idénticas, solo la mejor
                continue
            vistos.add((x["tf"], x["nombre"]))
            m["cartera"], m["universo"] = f"{x['nombre']} {x['tf']}", x["simbolos"]
            dentro = 0
            for s in x["simbolos"]:
                if libres is not None and nuevas >= libres:
                    break
                if al.alta_estrategia(s, x["tf"], x["nombre"], x["params"], "incubadora", m, ahora):
                    nuevas, dentro = nuevas + 1, dentro + 1
            if dentro:
                al.evento(ahora, "Laboratorio", "alta", f"Cartera {x['nombre'].replace('_', ' ')} {x['tf']}: {dentro} bots entran en incubadora{marca}, "
                          f"todos con los mismos parámetros (Sharpe de la cartera en reserva {x['reserva']['sharpe']:.2f}).")
            continue
        if libres is not None and nuevas >= libres:
            break
        eid = al.alta_estrategia(x["simbolo"], x["tf"], x["nombre"], x["params"], "incubadora", m, ahora)
        if eid:
            nuevas += 1
            al.evento(ahora, "Laboratorio", "alta", f"#{eid} {x['nombre']} {x['simbolo']} {x['tf']}: entra en incubadora{marca} "
                                                     f"(Sharpe en reserva {x['reserva']['sharpe']:.2f}).")
    al.commit()
    return nuevas


def _guardar_informe(resultado: dict, cfg: dict, nombre: str, titulo: str) -> Path:
    carpeta = Path(cfg["rutas"]["informes"])
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.json").write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
    return report.generar(resultado, cfg, carpeta / f"{nombre}.html", titulo)


def _imprimir_embudo(r: dict):
    for etapa, n in r["embudo"]:
        print(f"  {etapa:34s} {n}")
    if r["placebo"]:
        print(f"  {'hallazgos distintos':34s} {r['hallazgos']}")
        print(f"  {'hallazgos en ruido (por ronda)':34s} {r['placebo']}")
    print("\n" + r["veredicto"])


# ------------------------------------------------------------------ comandos


def cmd_descargar(cfg, args):
    ex = data.crear_exchange(cfg["exchange"])
    malos = auto_mod.actualizar_datos(ex, cfg, aviso=print)
    if malos:
        print("\nEl exchange no reconoce:", ", ".join(malos))
        print("Perpetuos disponibles:", ", ".join(data.perpetuos_disponibles(ex)[:80]))
        print("Corrige `simbolos` en config.yaml y vuelve a lanzar.")


def cmd_minar(cfg, args):
    datos = _cargar_datos(cfg)
    if not datos:
        return
    print(f"Minando {len(datos)} series ({1 + cfg['robustez']['control_ruido']['rondas']} rondas contando el control de ruido). Puede tardar una hora.")
    hecho = set()

    def progreso(simbolo, tf, nombre, n):
        if (simbolo, tf) not in hecho:
            hecho.add((simbolo, tf))
            print(f"  {simbolo} {tf}...", flush=True)

    ahora = _ahora()
    al = Almacen(cfg["rutas"]["bd"])
    ronda, pesos = al.get("rondas_mineria", 0), rrhh.pesos(al)
    costes = departamentos.costes_con_medidas(al, cfg)
    al.cerrar()
    cfg = json.loads(json.dumps(cfg))
    cfg["costes"] = costes                    # el coste por moneda que ha medido Ejecución (el ruido se simula con el mismo)
    cfg["mineria"]["semilla"] += ronda          # cada ronda explora combinaciones distintas
    r = pipeline.ejecutar(datos, cfg, progreso, pesos=pesos)
    r["fecha"] = f"{ahora:%Y-%m-%d %H:%M} UTC"
    print()
    _imprimir_embudo(r)
    sin_evidencia = r["supervivientes"] > 0 and not r["evidencia"]
    al = Almacen(cfg["rutas"]["bd"])
    al.set("rondas_mineria", ronda + 1)
    rrhh.anotar_mineria(al, r)
    nuevas = 0
    if r["supervivientes"] and (not sin_evidencia or args.forzar):
        nuevas = _registrar(al, r, ahora, cfg["incubadora"]["max_estrategias"], sin_evidencia)
        print(f"{nuevas} estrategias nuevas en la incubadora.")
    elif sin_evidencia:
        print("No se manda nada a la incubadora (usa --forzar si aun así quieres incubarlas).")
    informe = _guardar_informe(r, cfg, f"mineria_{ahora:%Y%m%d_%H%M}", "Informe de minería")
    al.set("ultima_mineria", {"ts": str(ahora), "embudo": r["embudo"], "placebo": r["placebo"], "veredicto": r["veredicto"],
                              "supervivientes": r["supervivientes"], "nuevas": nuevas, "informe": str(informe)})
    al.evento(ahora, "Laboratorio", "mineria", f"Ronda de minería terminada: {r['pruebas']} combinaciones, {r['supervivientes']} supervivientes, "
                                                f"{nuevas} nuevas a incubadora. {r['veredicto']}")
    al.cerrar()
    print("Informe:", informe)


def cmd_incubar(cfg, args):
    al = Almacen(cfg["rutas"]["bd"])
    mesa = Mesa(cfg, al, FeedCCXT(data.crear_exchange(cfg["exchange"]), cfg["costes"]["funding_8h"]))
    print("Mesa de papel en marcha (Ctrl+C para parar). Nada de esto mueve dinero real.")
    while True:
        ahora = _ahora()
        try:
            r = mesa.ciclo(ahora)
            if al.get("ultimo_comite") != str(ahora.date()):
                print(f"{ahora:%H:%M}", comite_mod.reunir(mesa, ahora)["resumen"])
                al.set("ultimo_comite", str(ahora.date()))
                al.commit()
            print(f"{ahora:%Y-%m-%d %H:%M:%S}  estrategias {r['estrategias']}  órdenes {r['ordenes']}  fondo {r['equity_fondo']:,.2f}"
                  + (f"  [{r['bloqueo']}]" if r["bloqueo"] else ""), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # un fallo de red no debe tumbar la mesa
            print(f"{ahora:%H:%M:%S}  error en el ciclo: {e}", flush=True)
        if args.una_vez:
            break
        time.sleep(args.intervalo)
    al.cerrar()


def cmd_incubar_ultima(cfg, args):
    """Manda a la incubadora, marcadas como "a prueba", las supervivientes de la última minería aunque no hubiera evidencia."""
    informes = sorted(Path(cfg["rutas"]["informes"]).glob("mineria_*.json"))
    if not informes:
        print("No hay ninguna minería guardada todavía.")
        return
    r = json.loads(informes[-1].read_text(encoding="utf-8"))
    media = sum(r["placebo"]) / len(r["placebo"]) if r.get("placebo") else None
    # informes antiguos no traen "evidencia": se aplica la regla que tenían (el doble que la media del ruido)
    sin_evidencia = not r["evidencia"] if "evidencia" in r else (media is not None and r["supervivientes"] <= 2 * media)
    al = Almacen(cfg["rutas"]["bd"])
    ahora = _ahora()
    n = _registrar(al, r, ahora, cfg["incubadora"]["max_estrategias"], sin_evidencia)
    if n and sin_evidencia:
        al.evento(ahora, "Laboratorio", "aviso", f"{n} estrategias entran en incubadora solo para observarlas en papel: en la minería sobrevivieron "
                                                 f"{r['supervivientes']} y el ruido puro dio {r['placebo']}, así que no se distinguen de la suerte.")
    ultima = al.get("ultima_mineria")
    if ultima:
        al.set("ultima_mineria", {**ultima, "nuevas": ultima.get("nuevas", 0) + n})
    al.cerrar()
    print(f"{n} estrategias a la incubadora" + (" (a prueba, sin evidencia estadística)." if sin_evidencia else "."))


def cmd_biblioteca(cfg, args):
    al = Almacen(cfg["rutas"]["bd"])
    for nombre in biblioteca.MODELOS:        # a mano se repite siempre, aunque no haya pasado el plazo
        previo = al.get(f"biblioteca:{nombre}")
        if previo:
            al.set(f"biblioteca:{nombre}", {**previo, "ts": "2000-01-01"})
    al.commit()
    n = biblioteca.contratar(al, cfg, _ahora(), aviso=lambda m: print(m, "\n"))
    al.cerrar()
    print(f"{n} bots nuevos en la incubadora." if n else "Ningún bot nuevo (o ya estaban contratados, o no hay velas diarias descargadas todavía).")


def cmd_auto(cfg, args):
    auto_mod.ejecutar(cfg, args.config, args.intervalo, args.sin_panel)


def cmd_panel(cfg, args):
    print(f"Panel en http://localhost:{cfg['panel']['puerto']} (Ctrl+C para cerrar)")
    panel.arrancar(cfg, en_hilo=False)


def cmd_comite(cfg, args):
    al = Almacen(cfg["rutas"]["bd"])
    mesa = Mesa(cfg, al, None)
    print(comite_mod.reunir(mesa, _ahora())["resumen"])
    al.cerrar()


def cmd_estado(cfg, args, ahora=None):
    al = Almacen(cfg["rutas"]["bd"])
    mesa = Mesa(cfg, al, None)
    ahora = ahora or _ahora()
    kill = al.get("kill", {})
    print(f"Fondo (papel): {mesa.equity_fondo():,.2f}  |  caja {mesa.caja():,.2f}  |  capital inicial {cfg['riesgos']['capital']:,.2f}")
    print("Kill switch:", f"ACTIVO ({kill.get('motivo')})" if kill.get("activo") else "inactivo",
          "| pausa por pérdida diaria" if mesa.riesgos.pausado(ahora) else "")
    for estado, titulo in (("aprobada", "Con capital"), ("incubadora", "Incubadora")):
        ests = al.estrategias((estado,))
        print(f"\n{titulo} ({len(ests)})")
        for e in ests:
            c = al.cuenta(e["id"])
            if not c:
                print(f"  #{e['id']:<3d} {e['nombre']:20s} {e['simbolo']:15s} {e['tf']:3s}  aún sin operar")
                continue
            s = estadisticas(al.curva(e["id"], c["alta"]), c, ahora)
            print(f"  #{e['id']:<3d} {e['nombre']:20s} {e['simbolo']:15s} {e['tf']:3s}  {s['dias']:5.1f} d  {s['trades']:3d} ops  "
                  f"{s['retorno']:+7.2%}  caída {s['dd_max']:5.1%}  Sharpe {s['sharpe']:5.2f}  pos {c['pos']:+.2f}x"
                  + (f"  capital {c['equity']:,.0f}" if c["fase"] == "fondo" else ""))
    print(f"\nDescartadas: {len(al.estrategias(('descartada',)))}")
    print("\nÚltimos eventos")
    for ev in al.eventos(args.eventos if hasattr(args, "eventos") else 12):
        print(f"  {ev['ts'][:16]}  {ev['origen']:11s} {ev['mensaje']}")
    al.cerrar()


def cmd_kill(cfg, args):
    al = Almacen(cfg["rutas"]["bd"])
    mesa = Mesa(cfg, al, None)
    if args.reactivar:
        mesa.riesgos.reactivar(_ahora(), mesa.equity_fondo())
        print("Kill switch reactivado. La caída máxima se mide desde el capital actual.")
    else:
        mesa.riesgos.activar_kill(_ahora(), "activado a mano")
        print("Kill switch activado. La mesa cerrará todas las posiciones del fondo en su próximo ciclo.")
    al.cerrar()


def cmd_demo(cfg, args):
    """Todo el circuito con datos inventados, para ver que funciona antes de conectar nada."""
    cfg = json.loads(json.dumps(cfg))
    cfg["simbolos"], cfg["timeframes"] = ["TENDENCIA-A", "TENDENCIA-B", "RUIDO"], ["1h"]
    cfg["mineria"].update(pruebas_por_estrategia=40, modo="individual")
    cfg["robustez"]["control_ruido"]["rondas"] = 9
    cfg["rutas"] = {"datos": "demo/datos", "bd": "demo/demo.db", "informes": "demo"}
    Path("demo").mkdir(exist_ok=True)
    Path(cfg["rutas"]["bd"]).unlink(missing_ok=True)
    series = {"TENDENCIA-A": data.sintetico(26000, "tendencial", semilla=1), "TENDENCIA-B": data.sintetico(26000, "tendencial", semilla=2),
              "RUIDO": data.sintetico(26000, "aleatorio", semilla=3)}
    datos = {(s, "1h"): (df, None) for s, df in series.items()}
    print("1/3 Minería sobre dos series con tendencia real y una de ruido puro, más 9 rondas de control (dos minutos aprox.)...")
    r = pipeline.ejecutar(datos, cfg, aviso=lambda m: print("   ", m))
    r["fecha"] = "Demo con datos sintéticos"
    _imprimir_embudo(r)
    por_serie = {s: sum(1 for x in r["resultados"] if x["sobrevive"] and x["simbolo"] == s) for s in series}
    print("Supervivientes por serie:", por_serie, "(en RUIDO lo correcto es 0 o casi)")

    print("\n2/3 Incubadora: se reproduce vela a vela el último 20 % del histórico, con comité diario...")
    al = Almacen(cfg["rutas"]["bd"])
    df0 = series["RUIDO"]
    inicio = int(len(df0) * 0.8)
    _registrar(al, r, df0.index[inicio])
    informe = _guardar_informe(r, cfg, "informe_demo", "Informe de minería (demo sintética)")
    al.set("ultima_mineria", {"ts": str(df0.index[inicio]), "embudo": r["embudo"], "placebo": r["placebo"], "veredicto": r["veredicto"],
                              "supervivientes": r["supervivientes"], "nuevas": r["supervivientes"], "informe": str(informe)})
    mesa = Mesa(cfg, al, FeedReplay({k: v[0] for k, v in datos.items()}, cfg["costes"]["funding_8h"]))
    dia = None
    for ts in df0.index[inicio:]:
        mesa.ciclo(ts)
        if ts.date() != dia:
            dia = ts.date()
            comite_mod.reunir(mesa, ts)
    al.cerrar()

    print("\n3/3 Estado final\n")
    args.eventos = 8
    cmd_estado(cfg, args, ahora=df0.index[-1])
    print("\nInforme:", informe)
    if args.panel:
        print(f"Panel de la demo en http://localhost:{cfg['panel']['puerto']} (Ctrl+C para cerrar)")
        panel.arrancar(cfg, reloj=lambda: df0.index[-1], en_hilo=False)


def main(argv=None):
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m fondo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--panel", action="store_true", help="al terminar, abre el panel con los datos de la demo")
    sub.add_parser("descargar")
    m = sub.add_parser("minar")
    m.add_argument("--forzar", action="store_true", help="incubar aunque el control de ruido diga que no hay evidencia")
    au = sub.add_parser("auto")
    au.add_argument("--intervalo", type=int, default=60, help="segundos entre ciclos")
    au.add_argument("--sin-panel", action="store_true")
    sub.add_parser("panel")
    sub.add_parser("incubar-ultima")
    sub.add_parser("biblioteca")
    i = sub.add_parser("incubar")
    i.add_argument("--una-vez", action="store_true", help="un solo ciclo y salir")
    i.add_argument("--intervalo", type=int, default=60, help="segundos entre ciclos")
    sub.add_parser("comite")
    e = sub.add_parser("estado")
    e.add_argument("--eventos", type=int, default=12)
    k = sub.add_parser("kill")
    k.add_argument("--reactivar", action="store_true")
    args = ap.parse_args(argv)
    cfg = config.cargar(args.config)
    {"demo": cmd_demo, "auto": cmd_auto, "panel": cmd_panel, "incubar-ultima": cmd_incubar_ultima, "biblioteca": cmd_biblioteca, "descargar": cmd_descargar, "minar": cmd_minar, "incubar": cmd_incubar,
     "comite": cmd_comite, "estado": cmd_estado, "kill": cmd_kill}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
