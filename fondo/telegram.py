"""Telegram: avisos de lo importante y control básico desde el móvil.

Se activa solo si existe el archivo `telegram_token.txt` en la carpeta del fondo, con el token que
da @BotFather al crear un bot. La primera persona que le escriba /start en los 15 minutos siguientes
al arranque queda vinculada; a partir de ahí el bot solo obedece a ese chat.

Órdenes: /estado, /liga, /parar y /reanudar (las dos últimas piden /confirmar), /ayuda.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

import pandas as pd

from . import panel
from .paper import Mesa
from .store import Almacen

AVISAR = ("kill", "pausa", "modo_seguro", "acta", "decaimiento", "desvio", "convocatoria", "resultado", "cierre", "error", "reinicio", "regimen", "calidad", "descuadre", "costes", "sentimiento", "alerta", "conclusion", "semanal", "caida")
AYUDA = ("/estado: cómo va el fondo\n/liga: ranking de bots\n/analisis: mercado, sentimiento, noticias y debate del día\n/parar: cerrar todo y dejar de operar\n"
         "/reanudar: volver a operar\n/ayuda: esta lista")


def leer_token(cfg: dict) -> str | None:
    if os.environ.get("TELEGRAM_TOKEN", "").strip():        # en la nube, como variable de entorno
        return os.environ["TELEGRAM_TOKEN"].strip()
    ruta = Path(cfg["rutas"]["bd"]).resolve().parent / "telegram_token.txt"
    if not ruta.exists():
        return None
    lineas = [x.strip() for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
    return lineas[0] if lineas else None


def _pedir(url: str, datos: dict, espera: float) -> dict:
    peticion = urllib.request.Request(url, data=json.dumps(datos).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=espera) as r:
        return json.loads(r.read())


def _pct(x: float, d: int = 2) -> str:
    return f"{x * 100:+.{d}f} %".replace(".", ",")


def _dinero(x: float) -> str:
    """10000.5 -> '10.000,50 $' (formato español)."""
    return f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " $"


def _rodaje(dias: float) -> str:
    return f"{dias:.0f} d" if dias >= 1 else f"{dias * 24:.0f} h"


def liga(e: dict, n: int = 10) -> str:
    bots = sorted((b for b in e["estrategias"] if b.get("dias") is not None), key=lambda b: -b["retorno"])
    if not bots:
        return "Todavía no hay bots con rodaje."
    filas = [f"{i}. {b['apodo']} (n.º {b['id']}, {b['nombre'].replace('_', ' ')} {b['simbolo'].split('/')[0]}): {_pct(b['retorno'])} en {_rodaje(b['dias'])}"
             + (", con capital" if b["estado"] == "aprobada" else "") for i, b in enumerate(bots[:n], 1)]
    return "Liga de bots\n" + "\n".join(filas)


def resumen(e: dict) -> str:
    f, r = e["fondo"], e["riesgos"]
    situacion = "PARADO" if r["kill"] else "en pausa hasta mañana" if r["pausa"] else "operando"
    lineas = [f"Fondo ({e['modo']}): {_dinero(f['equity'])}", f"Hoy {_pct(f['hoy'])}, desde el inicio {_pct(f['total'])}",
              f"Situación: {situacion}", f"Plantilla: {e['plantilla']['hay']} de {e['plantilla']['objetivo']} bots, "
              f"{sum(1 for b in e['estrategias'] if b['estado'] == 'aprobada')} con capital"]
    macro = (e.get("apoyo") or {}).get("macro")
    if macro:
        lineas.append(f"Mercado: {macro['tendencia']}, {macro['clima']}")
    if e["aprendizaje"]["en_curso"]:
        lineas.append("El laboratorio está minando ahora.")
    return "\n".join(lineas)


def analisis(e: dict) -> str:
    apoyo, an = e.get("apoyo") or {}, e.get("analistas") or {}
    lineas = [x["texto"] for x in (apoyo.get("macro"), an.get("sentimiento")) if x]
    n = an.get("noticias")
    if n:
        lineas.append(n["texto"])
        lineas += [f"· {t['titulo']} ({t['fuente']})" for t in n["destacados"][:4]]
    d = an.get("debate")
    if d:
        lineas += [f"Debate del {d['fecha']}", f"Alcista: {d['alcista']}", f"Bajista: {d['bajista']}", f"Moderador: {d['conclusion']}",
                   "(El debate lo escribe un modelo de lenguaje: es opinión y no decide nada en el fondo.)"]
    else:
        lineas.append("Sin debate: hace falta la clave de un modelo de lenguaje en llm_clave.txt.")
    return "\n\n".join(lineas) if lineas else "Los analistas aún no han hecho su primera ronda."


class Telegram:
    def __init__(self, token: str, cfg: dict, pedir=_pedir, reloj=None):
        self.url, self.cfg, self.pedir, self._token = f"https://api.telegram.org/bot{token}/", cfg, pedir, token
        self.reloj = reloj or (lambda: pd.Timestamp.now(tz="UTC").floor("s"))
        self.inicio, self.offset, self.pendiente = self.reloj(), None, None

    def _llamar(self, metodo: str, espera: float = 15, **datos) -> dict:
        return self.pedir(self.url + metodo, datos, espera)

    def _motivo(self, e: Exception) -> str:
        """Descripción del fallo sin el token dentro, apta para enseñarla en el panel."""
        codigo = getattr(e, "code", None)
        if codigo == 401 or codigo == 404:
            return "Telegram no reconoce ese token: revisa que esté copiado entero y sin espacios."
        return f"{type(e).__name__}: {e}".replace(self._token, "***")[:200]

    def comprobar(self, al: Almacen) -> bool:
        """Pregunta a Telegram quién es el bot. Sirve para saber si el token vale y cómo se llama el bot."""
        try:
            yo = self._llamar("getMe").get("result", {})
            al.set("telegram_bot", yo.get("username"))
            al.set("telegram_error", None)
            ok = True
        except Exception as e:
            al.db.rollback()
            al.set("telegram_error", self._motivo(e))
            ok = False
        al.commit()
        return ok

    def enviar(self, chat, texto: str):
        self._llamar("sendMessage", chat_id=chat, text=texto[:3900])

    def enviar_archivo(self, chat, ruta, pie: str = ""):
        """Manda un archivo al chat (la copia semanal de la base). Formulario multipart hecho a mano: no hay más dependencias."""
        ruta, borde = Path(ruta), "----fondo" + os.urandom(8).hex()
        partes = [f'--{borde}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'.encode(),
                  f'--{borde}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{pie[:900]}\r\n'.encode("utf-8"),
                  f'--{borde}\r\nContent-Disposition: form-data; name="document"; filename="{ruta.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),
                  ruta.read_bytes(), f"\r\n--{borde}--\r\n".encode()]
        peticion = urllib.request.Request(self.url + "sendDocument", data=b"".join(partes), headers={"Content-Type": f"multipart/form-data; boundary={borde}"})
        with urllib.request.urlopen(peticion, timeout=120) as r:
            return json.loads(r.read())

    def vigilar(self, al: Almacen) -> str | None:
        """Vigilante: si la mesa lleva demasiado sin completar un ciclo, avisa (una vez), y vuelve a avisar cuando se recupera.
        Va en este hilo, aparte del de la mesa, justo para poder avisar cuando la mesa se ha quedado colgada."""
        chat, latido = al.get("telegram_chat"), al.get("latido")
        if not chat or not latido:
            return None
        minutos = (self.reloj() - pd.Timestamp(latido)).total_seconds() / 60.0
        avisado = al.get("vigilante:avisado")
        if minutos >= self.cfg["vigilante"]["minutos"] and avisado != latido:
            texto = (f"Vigilante: la mesa lleva {minutos:.0f} minutos sin completar un ciclo (el último, a las {pd.Timestamp(latido):%H:%M} UTC). "
                     "Puede ser un corte de red con el exchange o que el programa se haya quedado colgado.")
        elif minutos < 3 and avisado and avisado != latido:
            texto = "Vigilante: la mesa vuelve a ciclar con normalidad."
            latido = None
        else:
            return None
        self.enviar(chat, texto)
        al.set("vigilante:avisado", latido)
        al.commit()
        return texto

    # ------------------------------------------------------------ avisos
    def avisos(self, al: Almacen) -> int:
        """Manda al chat vinculado los eventos importantes que aún no se han enviado."""
        chat = al.get("telegram_chat")
        ultimo = al.db.execute("SELECT max(id) FROM eventos").fetchone()[0] or 0
        visto = al.get("telegram_evento")
        if not chat or visto is None:
            al.set("telegram_evento", ultimo)          # sin vincular no se acumula: al vincular no llega el historial entero
            al.commit()                                # sin esto la base se queda bloqueada para el resto de procesos
            return 0
        marcas = ",".join("?" * len(AVISAR))
        filas = al.db.execute(f"SELECT origen, mensaje FROM eventos WHERE id > ? AND tipo IN ({marcas}) ORDER BY id LIMIT 15", (visto, *AVISAR)).fetchall()
        if filas:
            self.enviar(chat, "\n\n".join(f"{f['origen']}: {f['mensaje']}" for f in filas))
        al.set("telegram_evento", ultimo)
        al.commit()
        return len(filas)

    # ------------------------------------------------------------ órdenes
    def atender(self, al: Almacen, espera: int = 0) -> int:
        r = self._llamar("getUpdates", espera=espera + 10, timeout=espera, **({"offset": self.offset} if self.offset else {}))
        for u in r.get("result", []):
            self.offset = u["update_id"] + 1
            m = u.get("message") or {}
            if m.get("text") and m.get("chat"):
                try:
                    self._mensaje(al, m["chat"]["id"], m["text"].strip())
                except Exception as e:
                    self.enviar(m["chat"]["id"], f"No he podido hacerlo: {type(e).__name__}: {e}")
        return len(r.get("result", []))

    def _mensaje(self, al: Almacen, chat, texto: str):
        orden = texto.split()[0].split("@")[0].lower()
        vinculado, ahora = al.get("telegram_chat"), self.reloj()
        if vinculado is None:
            if orden == "/start" and ahora - self.inicio <= pd.Timedelta(minutes=15):
                al.set("telegram_chat", chat)
                al.evento(ahora, "Sistema", "telegram", "Telegram vinculado: los avisos importantes llegarán a ese chat.")
                al.commit()
                return self.enviar(chat, "Vinculado. A partir de ahora te aviso de lo importante y solo obedezco a este chat.\n\n" + AYUDA)
            return self.enviar(chat, "Este bot aún no está vinculado. Reinicia el fondo y envíame /start en los 15 minutos siguientes.")
        if chat != vinculado:
            return self.enviar(chat, "Este bot ya está vinculado a otro chat.")
        mesa = Mesa(self.cfg, al, None)
        if orden == "/confirmar":
            accion, hasta = self.pendiente or (None, ahora)
            self.pendiente = None
            if accion is None or ahora > hasta:
                return self.enviar(chat, "No hay nada pendiente de confirmar.")
            if accion == "parar":
                mesa.riesgos.activar_kill(ahora, "parada desde Telegram")
            else:
                mesa.riesgos.reactivar(ahora, mesa.equity_fondo())
            al.commit()
            return self.enviar(chat, "Hecho: el fondo cerrará todo en su próximo ciclo y no operará hasta que lo reanudes." if accion == "parar"
                               else "Hecho: el fondo vuelve a operar.")
        if orden in ("/parar", "/reanudar"):
            self.pendiente = (orden[1:], ahora + pd.Timedelta(seconds=90))
            return self.enviar(chat, ("Vas a cerrar todas las posiciones del fondo y dejar de operar." if orden == "/parar" else "Vas a reanudar la operativa.")
                               + " Envía /confirmar en el próximo minuto y medio.")
        if orden in ("/estado", "/liga", "/analisis"):
            e = panel.estado(self.cfg, al, ahora)
            return self.enviar(chat, resumen(e) if orden == "/estado" else liga(e) if orden == "/liga" else analisis(e))
        self.enviar(chat, AYUDA)

    def escuchar(self):
        """Hilo aparte: atiende las órdenes en cuanto llegan (sondeo largo)."""
        al = Almacen(self.cfg["rutas"]["bd"])
        comprobado = False
        while True:
            try:
                if not comprobado:
                    comprobado = self.comprobar(al)
                self.atender(al, espera=25)
                self.vigilar(al)
                if al.get("telegram_error"):
                    al.set("telegram_error", None)
                    al.commit()
            except Exception as e:      # sin red, Telegram caído o token malo: se apunta el motivo y se reintenta
                try:
                    al.db.rollback()
                    motivo = self._motivo(e)
                    if al.get("telegram_error") != motivo:
                        al.set("telegram_error", motivo)
                        al.commit()
                except Exception:       # ni siquiera se puede apuntar: se reintenta igualmente
                    pass
                time.sleep(10)


def crear(cfg: dict) -> Telegram | None:
    token = leer_token(cfg)
    return Telegram(token, cfg) if token else None
