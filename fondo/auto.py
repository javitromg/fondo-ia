"""Modo automático: un solo proceso que lo hace todo sin que lo toques.

Cada minuto   marca a mercado, vigila riesgos y ejecuta las órdenes que tocan (en papel).
Cada hora     actualiza el histórico de velas y funding.
Cada día      reúne al comité: promociones, descartes y reparto de capital.
Cada semana   vuelve a minar con los datos más recientes y manda lo que sobreviva a la incubadora.
Siempre       sirve el panel en http://localhost:<puerto>.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd

from . import analistas, auditoria, biblioteca, comite, config, data, departamentos, panel, rrhh, telegram
from .store import FONDO
from .feeds import FeedCCXT
from .paper import Mesa
from .store import Almacen


def _ahora() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").floor("s")


def actualizar_datos(ex, cfg: dict, aviso=None) -> list[str]:
    """Baja lo que falte de cada serie. Devuelve los símbolos que el exchange no reconoce.
    Si una serie falla (un corte, un timeframe que el exchange no da), se avisa y se sigue con las demás."""
    malos, fallos = [], []
    for s in cfg["simbolos"]:
        for tf in cfg["timeframes"]:
            try:
                df = data.descargar_velas(ex, s, tf, config.historia(cfg, tf), cfg["rutas"]["datos"], cfg["exchange"])
                if aviso:
                    aviso(f"{s:14s} {tf:4s} {len(df):6d} velas" + (f"  {df.index[0]:%Y-%m-%d} a {df.index[-1]:%Y-%m-%d}" if len(df) else ""))
            except Exception as e:
                if type(e).__name__ == "BadSymbol":
                    malos.append(s)
                    break
                fallos.append(f"{s} {tf}: {type(e).__name__}: {e}")
        if s in malos:
            continue
        try:
            f = data.descargar_funding(ex, s, cfg["historia_dias"], cfg["rutas"]["datos"], cfg["exchange"])
            if aviso:
                aviso(f"{s:14s} funding {'sin histórico, se usará el valor fijo' if f is None else f'{len(f)} pagos'}")
        except Exception as e:
            fallos.append(f"{s} funding: {type(e).__name__}: {e}")
    if fallos:
        (aviso or print)(f"{len(fallos)} series no se han podido actualizar. Primera: {fallos[0]}")
    return malos


def _refrescar(cfg: dict):
    """Actualiza el histórico con su propia conexión, para poder hacerlo mientras la mesa sigue ciclando.
    Con los datos al día, la biblioteca revisa sus modelos publicados y contrata los que toque."""
    try:
        malos = actualizar_datos(data.crear_exchange(cfg["exchange"]), cfg)
        if malos:
            print("Símbolos que el exchange no reconoce (revisa config.yaml):", ", ".join(malos), flush=True)
    except Exception as e:
        print(f"No se pudo actualizar el histórico: {type(e).__name__}: {e}", flush=True)
    try:
        al = Almacen(cfg["rutas"]["bd"])
        try:
            departamentos.revisar_datos(al, cfg, _ahora())
            n = biblioteca.contratar(al, cfg, _ahora())
            if n:
                print(f"Biblioteca: {n} bots de modelos publicados entran en incubadora.", flush=True)
            analistas.ronda(al, cfg, _ahora(), modelo=analistas.crear_modelo(cfg))
        finally:
            al.cerrar()
    except Exception as e:
        print(f"La biblioteca no ha podido revisar sus modelos: {type(e).__name__}: {e}", flush=True)


def adoptar_informe(al: Almacen, cfg: dict):
    """Si hay un informe de minería más reciente que lo apuntado en la base (p. ej. una ronda lanzada a mano que no
    pudo guardar su resultado), lo da por bueno: actualiza el panel y, si traía evidencia, contrata a sus supervivientes."""
    import json

    informes = sorted(Path(cfg["rutas"]["informes"]).glob("mineria_*.json"))
    if not informes:
        return
    try:
        r = json.loads(informes[-1].read_text(encoding="utf-8"))
        ts = pd.Timestamp(r["fecha"].replace(" UTC", ""), tz="UTC")
    except Exception:
        return
    ultima = al.get("ultima_mineria")
    if ultima and pd.Timestamp(ultima["ts"]) >= ts - pd.Timedelta(minutes=2):
        return
    from .cli import _registrar          # aquí dentro para no cruzar las importaciones

    nuevas = _registrar(al, r, _ahora(), cfg["incubadora"]["max_estrategias"]) if r.get("evidencia") else 0
    rrhh.anotar_mineria(al, r)
    al.set("rondas_mineria", al.get("rondas_mineria", 0) + 1)
    al.set("ultima_mineria", {"ts": str(ts), "embudo": r["embudo"], "placebo": r.get("placebo", []), "veredicto": r["veredicto"],
                              "supervivientes": r["supervivientes"], "nuevas": nuevas, "informe": str(informes[-1].with_suffix(".html"))})
    al.evento(_ahora(), "Laboratorio", "mineria", f"Ronda de minería terminada: {r['pruebas']} combinaciones, {r['supervivientes']} supervivientes, "
                                                  f"{nuevas} nuevas a incubadora. {r['veredicto']}")
    al.commit()


def toca_minar(al: Almacen, cfg: dict, ahora: pd.Timestamp) -> bool:
    return rrhh.toca_convocatoria(al, cfg, ahora) is not None


def cierre_del_dia(mesa: Mesa, cfg: dict, ahora: pd.Timestamp) -> str:
    """Lo que pasa una vez al día: Auditoría revisa, el comité decide, los departamentos de apoyo informan y Dirección deja el resumen."""
    al = mesa.al
    try:
        auditoria.revisar(mesa, cfg, ahora)
    except Exception as e:                       # sin auditoría un día, el comité decide igual con sus reglas
        al.evento(ahora, "Auditoría", "error", f"No se ha podido auditar hoy: {type(e).__name__}: {e}")
    acta = comite.reunir(mesa, ahora)
    departamentos.ronda(al, cfg, ahora)
    equity = mesa.equity_fondo()
    ayer = al.curva(FONDO, ahora - pd.Timedelta(days=1))
    cambio = equity / ayer.iloc[0] - 1.0 if len(ayer) and ayer.iloc[0] > 0 else 0.0
    al.evento(ahora, "Dirección", "cierre", f"Cierre del día: patrimonio {equity:,.2f} $ ({cambio:+.2%} en 24 h), {al.contar('aprobada')} bots con capital, "
                                            f"{al.contar('incubadora')} en incubadora, {len(acta['descartadas'])} despedidos hoy.")
    al.commit()
    return acta["resumen"]


def ejecutar(cfg: dict, ruta_config: str, intervalo: int = 60, sin_panel: bool = False, ciclos: int | None = None):
    try:                                         # en la nube, un redespliegue manda SIGTERM: se sale limpio, con todo guardado
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    except ValueError:                           # solo se puede desde el hilo principal (en los tests no hace falta)
        pass
    al = Almacen(cfg["rutas"]["bd"])
    ex = data.crear_exchange(cfg["exchange"])
    mesa = Mesa(cfg, al, FeedCCXT(ex, cfg["costes"]["funding_8h"]))
    al.set("mineria_en_curso", None)
    latido = al.get("latido")
    if latido and (_ahora() - pd.Timestamp(latido)) > pd.Timedelta(minutes=5):      # no es un reinicio pedido: ha estado caído
        parado = _ahora() - pd.Timestamp(latido)
        cuanto = f"{parado.total_seconds() / 3600:.1f} horas" if parado > pd.Timedelta(hours=2) else f"{parado.total_seconds() / 60:.0f} minutos"
        al.evento(_ahora(), "Sistema", "caida", f"El fondo ha estado parado {cuanto}: el último ciclo fue el {pd.Timestamp(latido):%d/%m a las %H:%M} UTC. "
                                                 "Las posiciones en papel se han quedado como estaban y ahora se ponen al día.")
    if al.get("ultima_descarga") is not None:
        al.set("ultima_descarga", "")        # al arrancar se refrescan los datos enseguida (aparte, sin parar la mesa)
    adoptar_informe(al, cfg)
    al.evento(_ahora(), "Sistema", "inicio", f"Fondo en marcha en modo papel sobre {cfg['exchange']}.")
    n, objetivo = rrhh.plantilla(al), cfg["rrhh"]["plantilla_objetivo"]
    al.evento(_ahora(), "Selección", "plantilla", f"Plantilla: {n} de {objetivo} bots. " + ("Está completa." if n >= objetivo else
              f"Mientras falten, pediré al laboratorio una búsqueda extra cada {cfg['rrhh']['descanso_horas']} horas como mucho."))
    al.commit()
    departamentos.ronda(al, cfg, _ahora(), cierre=False)      # Macro, Cartera y Operaciones dicen cómo está la casa al abrir
    if not sin_panel:
        servidor = panel.arrancar(cfg)
        if servidor is not None:
            print(f"Panel: http://localhost:{servidor.server_address[1]}" + (" (con contraseña)" if panel.clave_panel(cfg) else ""), flush=True)
    print("Modo automático en marcha (Ctrl+C para parar). Opera en papel: no mueve dinero real.")
    tg = None
    registro = Path(cfg["rutas"]["informes"])
    registro.mkdir(parents=True, exist_ok=True)
    proceso, refresco = None, None
    senal_reinicio = Path(cfg["rutas"]["bd"]).resolve().parent / "REINICIAR"

    while True:
        ahora = _ahora()
        # un archivo llamado REINICIAR en la carpeta hace que el programa se cierre y INICIAR.bat lo vuelva a abrir
        # con el código nuevo. Se espera a que no haya una minería en marcha para no dejarla huérfana.
        if senal_reinicio.exists() and proceso is None:
            senal_reinicio.unlink()
            al.evento(ahora, "Sistema", "reinicio", "Reinicio para aplicar una actualización.")
            al.cerrar()
            print("Reinicio para aplicar una actualización.", flush=True)
            sys.exit(3)
        try:
            hora = f"{ahora:%Y-%m-%d %H}"
            if al.get("ultima_descarga") != hora and not (refresco and refresco.is_alive()):
                primera = al.get("ultima_descarga") is None
                al.set("ultima_descarga", hora)
                al.commit()
                if primera:                      # sin histórico no hay nada que minar: la primera descarga sí se espera
                    _refrescar(cfg)
                    ahora = _ahora()
                else:                            # las siguientes van aparte para no parar la mesa
                    refresco = threading.Thread(target=_refrescar, args=(cfg,), daemon=True)
                    refresco.start()

            if proceso is not None and proceso.poll() is not None:
                en_curso = al.get("mineria_en_curso") or {}
                ultima = al.get("ultima_mineria")
                terminada = proceso.returncode == 0 and ultima is not None and ultima["ts"] >= en_curso.get("inicio", "")
                al.set("mineria_en_curso", None)
                if terminada:
                    n, objetivo = rrhh.plantilla(al), cfg["rrhh"]["plantilla_objetivo"]
                    nuevas = (al.get("ultima_mineria") or {}).get("nuevas", 0)
                    al.evento(ahora, "Selección", "resultado", (f"{nuevas} bots contratados." if nuevas else "La búsqueda no ha dado candidatos fiables: no se contrata a nadie.")
                              + f" Plantilla: {n} de {objetivo}.")
                if not terminada:      # falló o salió sin minar (p. ej. sin datos): se reintenta mañana, no cada minuto
                    al.evento(ahora, "Laboratorio", "error", "La ronda de minería no se ha completado; mira informes/mineria.log. Se reintentará mañana.")
                    al.set("mineria_no_antes", str(ahora + pd.Timedelta(days=1)))
                al.commit()
                proceso = None
            motivo = rrhh.toca_convocatoria(al, cfg, ahora) if proceso is None else None
            if motivo:
                al.set("mineria_en_curso", {"inicio": str(ahora)})
                al.evento(ahora, "Selección", "convocatoria", f"Convocatoria: {motivo}. Se pide al laboratorio una ronda de búsqueda.")
                al.evento(ahora, "Laboratorio", "mineria", "Empieza una ronda de minería con los datos más recientes.")
                al.commit()
                with open(registro / "mineria.log", "a", encoding="utf-8") as log:
                    proceso = subprocess.Popen([sys.executable, "-m", "fondo", "--config", ruta_config, "minar"], stdout=log, stderr=log)

            r = mesa.ciclo(ahora)
            al.set("latido", str(ahora))         # el vigilante y el panel miran esto para saber que la mesa sigue viva
            if al.get("ultimo_comite") != str(ahora.date()):
                print(f"{ahora:%H:%M}", cierre_del_dia(mesa, cfg, ahora))
                al.set("ultimo_comite", str(ahora.date()))
                al.commit()
            print(f"{ahora:%Y-%m-%d %H:%M:%S}  estrategias {r['estrategias']}  órdenes {r['ordenes']}  fondo {r['equity_fondo']:,.2f}"
                  + (f"  [{r['bloqueo']}]" if r["bloqueo"] else "") + ("  [minando]" if proceso else ""), flush=True)
            if tg is None:               # el token puede aparecer en cualquier momento: no hace falta reiniciar
                tg = telegram.crear(cfg)
                if tg:
                    threading.Thread(target=tg.escuchar, daemon=True).start()
                    falta = not al.get("telegram_chat")
                    al.evento(ahora, "Sistema", "telegram", "Telegram activado." + (" Envía /start a tu bot en los próximos 15 minutos para vincularlo." if falta else ""))
                    al.commit()
                    print("Telegram activado.", flush=True)
            if tg:
                try:
                    tg.avisos(al)
                    pendiente, chat = al.get("copia:enviar"), al.get("telegram_chat")
                    if pendiente and chat:           # la copia semanal de la base, fuera del servidor
                        al.set("copia:enviar", None)
                        al.commit()
                        if Path(pendiente).exists():
                            tg.enviar_archivo(chat, pendiente, "Copia de seguridad semanal de la base del fondo. Guárdala: con ella se puede reconstruir todo.")
                except Exception:        # Telegram caído no afecta al fondo
                    pass
        except KeyboardInterrupt:
            raise
        except Exception as e:   # un fallo de red no debe tumbar el fondo
            print(f"{ahora:%H:%M:%S}  error en el ciclo: {type(e).__name__}: {e}", flush=True)
        finally:
            try:
                al.commit()      # nada queda a medias entre ciclos: una escritura sin cerrar bloquea la base a los demás procesos
            except Exception:
                pass
        if ciclos is not None:
            ciclos -= 1
            if ciclos <= 0:
                al.cerrar()
                return
        time.sleep(max(1.0, intervalo - time.time() % intervalo))
