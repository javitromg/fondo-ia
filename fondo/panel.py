"""Panel en vivo: servidor web local que enseña el estado del fondo y permite parar todo.

Solo escucha en 127.0.0.1 (tu propio ordenador). Si algún día se despliega en un servidor,
hay que ponerle autenticación delante antes de abrirlo a internet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

from . import analistas, biblioteca, departamentos, rrhh
from .paper import Mesa, estadisticas
from .store import FONDO, Almacen

HTML = Path(__file__).with_name("panel.html")
ENTRAR = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fondo IA</title><style>
:root{--fondo:#f3f5f3;--panel:#fff;--tinta:#14242d;--tenue:#55676d;--linea:#d8dedc;--laton:#8a6a1f;--pierde:#b42b2b}
@media (prefers-color-scheme:dark){:root{--fondo:#10202b;--panel:#172c39;--tinta:#eef0ea;--tenue:#9fb0b5;--linea:#2a4352;--laton:#c9a24b;--pierde:#e66767}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--fondo);color:var(--tinta);font-family:Archivo,system-ui,"Segoe UI",sans-serif}
form{background:var(--panel);border-radius:10px;padding:1.6rem 1.5rem;width:min(22rem,calc(100vw - 2rem));box-sizing:border-box}
h1{font-size:1.2rem;margin:0 0 .3rem}p{color:var(--tenue);margin:0 0 1.1rem;font-size:.95rem}.error{color:var(--pierde)}
label{display:block;font-size:.9rem;margin-bottom:.3rem}
input{width:100%;box-sizing:border-box;font:inherit;padding:.55rem .7rem;border:1px solid var(--linea);border-radius:6px;background:var(--fondo);color:var(--tinta)}
button{margin-top:1rem;width:100%;font:inherit;font-weight:600;padding:.6rem;border:0;border-radius:6px;background:var(--tinta);color:var(--fondo);cursor:pointer}
input:focus-visible,button:focus-visible{outline:2px solid var(--laton);outline-offset:2px}
</style></head><body><form method="post" action="/entrar"><h1>Fondo IA</h1><p__CLASE__>__MENSAJE__</p>
<label for="clave">Contraseña</label><input id="clave" name="clave" type="password" autocomplete="current-password" autofocus required>
<button>Entrar</button></form></body></html>"""
INTENTOS: dict[str, list[float]] = {}        # fallos de contraseña recientes por dirección, para frenar a quien prueba a ciegas


def clave_panel(cfg: dict) -> str | None:
    """Contraseña del panel: variable FONDO_CLAVE_PANEL o, en casa, un archivo panel_clave.txt junto a la base. Sin ella, el panel va abierto."""
    if os.environ.get("FONDO_CLAVE_PANEL", "").strip():
        return os.environ["FONDO_CLAVE_PANEL"].strip()
    ruta = Path(cfg["rutas"]["bd"]).resolve().parent / "panel_clave.txt"
    if ruta.exists():
        lineas = [x.strip() for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]
        return lineas[0] if lineas else None
    return None


def _firma(clave: str, caduca: int) -> str:
    return hmac.new(hashlib.sha256(("fondo-panel:" + clave).encode()).digest(), str(caduca).encode(), hashlib.sha256).hexdigest()


def sesion_nueva(clave: str, dias: float, ahora: float | None = None) -> str:
    caduca = int((time.time() if ahora is None else ahora) + dias * 86400)
    return f"{caduca}.{_firma(clave, caduca)}"


def sesion_valida(clave: str, galleta: str, ahora: float | None = None) -> bool:
    caduca, _, firma = (galleta or "").partition(".")
    return caduca.isdigit() and int(caduca) > (time.time() if ahora is None else ahora) and hmac.compare_digest(firma, _firma(clave, int(caduca)))


ESTATICOS = Path(__file__).with_name("static")
PERMITIDOS = {"three.module.min.js", "OrbitControls.js", "RoomEnvironment.js", "RoundedBoxGeometry.js", "BufferGeometryUtils.js", "oficina.js"}
# apodo de cada bot: el mismo en el panel, en la sala y en Telegram
NOMBRES = ["Lucía", "Mateo", "Vera", "Hugo", "Nora", "Izan", "Alba", "Leo", "Carla", "Bruno", "Irene", "Unai", "Elsa", "Marc", "Olaia", "Dario", "Aitana",
           "Pol", "Jimena", "Enzo", "Laia", "Iker", "Vega", "Saúl", "Noa", "Biel", "Candela", "Jon", "Ainhoa", "Teo", "Mara", "Aleix", "Lola", "Guille",
           "Nerea", "Roc", "Daniela", "Asier", "Clara", "Joel"]


def _reducir(serie: pd.Series, n: int) -> pd.Series:
    if len(serie) <= n:
        return serie
    paso = len(serie) / n
    idx = sorted({int(i * paso) for i in range(n)} | {len(serie) - 1})
    return serie.iloc[idx]


def estado(cfg: dict, al: Almacen, ahora: pd.Timestamp) -> dict:
    mesa = Mesa(cfg, al, None)
    lim = cfg["riesgos"]
    equity, caja = mesa.equity_fondo(), mesa.caja()
    inicio = al.get("inicio_dia") or {"equity": equity}
    pico = max(al.get("pico_fondo", equity), equity)
    kill = al.get("kill", {})

    estrategias, bruta, neta, por_simbolo = [], 0.0, 0.0, {}
    for e in al.estrategias(("aprobada", "incubadora")):
        c = al.cuenta(e["id"])
        fila = {"id": e["id"], "apodo": NOMBRES[e["id"] % len(NOMBRES)], "nombre": e["nombre"], "simbolo": e["simbolo"], "tf": e["tf"], "estado": e["estado"],
                "params": e["params"], "reserva": (e["metricas"].get("reserva") or {}).get("sharpe"),
                "sin_evidencia": bool(e["metricas"].get("sin_evidencia")), "cartera": e["metricas"].get("cartera"),
                "publicado": e["metricas"].get("origen") == "publicado", "fuente": e["metricas"].get("fuente"),
                "auditoria": al.get(f"auditoria:{e['id']}")}
        if c:
            curva = al.curva(e["id"], c["alta"])
            s = estadisticas(curva, c, ahora)
            fila.update(dias=s["dias"], trades=s["trades"], retorno=s["retorno"], dd=s["dd_max"], sharpe=s["sharpe"], pos=c["pos"],
                        capital=c["equity"] if c["fase"] == "fondo" else None, precio=c["precio"],
                        racha=c.get("racha") or 0, pausa_hasta=c.get("pausa_hasta"),
                        curva=[round(float(v), 5) for v in _reducir(curva, 40)])
            if c["fase"] == "fondo" and equity > 0:
                x = c["pos"] * c["equity"] / equity
                bruta, neta = bruta + abs(x), neta + x
                por_simbolo[e["simbolo"]] = por_simbolo.get(e["simbolo"], 0.0) + x
        estrategias.append(fila)

    pesos = rrhh.pesos(al)
    curva_fondo = _reducir(al.curva(FONDO), 300)
    ultima = al.get("ultima_mineria")
    proxima = None
    if ultima:
        proxima = str(pd.Timestamp(ultima["ts"]) + pd.Timedelta(days=cfg["aprendizaje"]["cada_dias"]))
    return {
        "ahora": str(ahora), "exchange": cfg["exchange"], "modo": "papel", "capacidades": ["comite"],
        "telegram": {"vinculado": bool(al.get("telegram_chat")), "bot": al.get("telegram_bot"), "error": al.get("telegram_error")},
        "departamentos": [f[0] for f in al.db.execute("SELECT DISTINCT origen FROM eventos")],
        "plantilla": {"hay": rrhh.plantilla(al), "objetivo": cfg["rrhh"]["plantilla_objetivo"]},
        "familias": [{"nombre": n, **v, "peso": pesos[n]} for n, v in rrhh.historial(al).items()],
        "fondo": {"equity": equity, "caja": caja, "capital": lim["capital"], "hoy": equity / inicio["equity"] - 1.0 if inicio["equity"] else 0.0,
                  "total": equity / lim["capital"] - 1.0, "caida": 1.0 - equity / pico if pico else 0.0,
                  "invertido": 1.0 - caja / equity if equity else 0.0},
        "riesgos": {
            "kill": bool(kill.get("activo")), "motivo": kill.get("motivo"), "pausa": mesa.riesgos.pausado(ahora),
            "limites": [
                {"nombre": "Pérdida del día", "uso": max(0.0, 1.0 - equity / inicio["equity"]) if inicio["equity"] else 0.0, "max": lim["perdida_diaria_max"], "pct": True},
                {"nombre": "Caída desde máximos", "uso": max(0.0, 1.0 - equity / pico) if pico else 0.0, "max": lim["caida_max"], "pct": True},
                {"nombre": "Exposición bruta", "uso": bruta, "max": lim["exposicion_bruta_max"], "pct": False},
                {"nombre": "Exposición neta", "uso": abs(neta), "max": lim["exposicion_neta_max"], "pct": False},
            ],
            "por_simbolo": [{"simbolo": k, "expo": v} for k, v in sorted(por_simbolo.items(), key=lambda kv: -abs(kv[1]))],
            "simbolo_max": lim["exposicion_simbolo_max"],
        },
        "curva": [[str(t), round(float(v), 2)] for t, v in curva_fondo.items()],
        "estrategias": estrategias,
        "descartadas": al.contar("descartada"),
        "biblioteca": biblioteca.estado(al),
        "protegido": clave_panel(cfg) is not None,
        "latido": al.get("latido"),
        "sin_ciclar_s": None if al.get("latido") is None else int((ahora - pd.Timestamp(al.get("latido"))).total_seconds()),
        "apoyo": departamentos.estado(al),
        "analistas": analistas.estado(al),
        "eventos": [{"id": ev["id"], "ts": ev["ts"], "origen": ev["origen"], "tipo": ev["tipo"], "mensaje": ev["mensaje"]} for ev in al.eventos(150)],
        "aprendizaje": {"ultima": ultima, "proxima": proxima, "en_curso": al.get("mineria_en_curso"), "cada_dias": cfg["aprendizaje"]["cada_dias"]},
    }


def _manejador(cfg: dict, reloj):
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):   # sin ruido en la consola
            pass

        def _enviar(self, codigo: int, cuerpo: bytes, tipo: str, cache: bool = False):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _quien(self) -> str:
            return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

        def _dentro(self) -> bool:
            clave = clave_panel(cfg)
            if clave is None:
                return True
            for trozo in (self.headers.get("Cookie") or "").split(";"):
                nombre, _, valor = trozo.strip().partition("=")
                if nombre == "fondo_sesion" and sesion_valida(clave, valor):
                    return True
            return False

        def _entrar(self, codigo: int, mensaje: str, error: bool = False, galleta: str | None = None):
            cuerpo = ENTRAR.replace("__MENSAJE__", mensaje).replace("__CLASE__", ' class="error"' if error else "").encode("utf-8")
            self.send_response(codigo)
            if galleta is not None:
                self.send_header("Set-Cookie", galleta)
            if codigo == 303:
                self.send_header("Location", "/")
                cuerpo = b""
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _galleta(self, valor: str, segundos: int) -> str:
            seguro = "; Secure" if self.headers.get("X-Forwarded-Proto", "").startswith("https") else ""
            return f"fondo_sesion={valor}; Max-Age={segundos}; Path=/; HttpOnly; SameSite=Strict{seguro}"

        def _json(self, obj, codigo=200):
            self._enviar(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            try:
                self.path = self.path.split("?")[0]
                if self.path == "/salud":                      # para el servidor: ¿sigue vivo y ciclando? No cuenta nada del fondo
                    al = Almacen(cfg["rutas"]["bd"])
                    try:
                        latido = al.get("latido")
                    finally:
                        al.cerrar()
                    sin = None if latido is None else int((reloj() - pd.Timestamp(latido)).total_seconds())
                    return self._json({"ok": True, "segundos_sin_ciclo": sin})
                if self.path == "/entrar":
                    return self._entrar(303, "") if self._dentro() else self._entrar(200, "Este panel pide contraseña.")
                if not self._dentro():
                    return self._entrar(200, "Este panel pide contraseña.") if self.path in ("/", "/index.html") else self._json({"error": "sin sesión"}, 401)
                if self.path in ("/", "/index.html"):
                    return self._enviar(200, HTML.read_bytes(), "text/html; charset=utf-8")
                if self.path.startswith("/static/"):          # la oficina 3D y su biblioteca: solo archivos de esa carpeta
                    ruta = ESTATICOS / self.path[len("/static/"):]
                    if ruta.name in PERMITIDOS and ruta.parent == ESTATICOS and ruta.is_file():
                        return self._enviar(200, ruta.read_bytes(), "text/javascript; charset=utf-8", cache=not ruta.name.startswith("oficina"))
                    return self._enviar(404, b"No encontrado", "text/plain; charset=utf-8")
                if self.path == "/api/estado":
                    al = Almacen(cfg["rutas"]["bd"])
                    try:
                        return self._json(estado(cfg, al, reloj()))
                    finally:
                        al.cerrar()
                if self.path == "/informe":
                    al = Almacen(cfg["rutas"]["bd"])
                    ultima = al.get("ultima_mineria") or {}
                    al.cerrar()
                    ruta = Path(ultima.get("informe", ""))
                    base = Path(cfg["rutas"]["informes"]).resolve()
                    if ruta.is_file() and base in ruta.resolve().parents:
                        return self._enviar(200, ruta.read_bytes(), "text/html; charset=utf-8")
                    return self._enviar(404, "Todavía no hay ningún informe de minería.".encode("utf-8"), "text/plain; charset=utf-8")
                self._enviar(404, b"No encontrado", "text/plain; charset=utf-8")
            except Exception as e:
                self._json({"error": str(e)}, 500)

        def do_POST(self):
            if self.path == "/entrar":
                clave, quien, ahora = clave_panel(cfg), self._quien(), time.time()
                if clave is None:
                    return self._entrar(303, "")
                fallos = INTENTOS[quien] = [t for t in INTENTOS.get(quien, []) if ahora - t < 900]
                if len(fallos) >= 5:
                    return self._entrar(429, "Demasiados intentos. Espera un cuarto de hora.", True)
                cuerpo = self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 4096)).decode("utf-8", "replace")
                dada = (urllib.parse.parse_qs(cuerpo).get("clave") or [""])[0]
                if hmac.compare_digest(hashlib.sha256(dada.encode()).digest(), hashlib.sha256(clave.encode()).digest()):
                    INTENTOS.pop(quien, None)
                    dias = cfg["panel"].get("sesion_dias", 30)
                    return self._entrar(303, "", galleta=self._galleta(sesion_nueva(clave, dias), int(dias * 86400)))
                fallos.append(ahora)
                return self._entrar(401, "Esa contraseña no es.", True)
            if self.path == "/salir":
                return self._entrar(200, "Sesión cerrada.", galleta=self._galleta("", 0))
            if not self._dentro():
                return self._json({"error": "sin sesión"}, 401)
            # la cabecera propia impide que otra web dispare esto desde el navegador
            if self.path not in ("/api/kill", "/api/comite") or self.headers.get("X-Fondo") != "1":
                return self._json({"error": "petición no válida"}, 400)
            al = None
            try:
                datos = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                al = Almacen(cfg["rutas"]["bd"])
                mesa, ahora = Mesa(cfg, al, None), reloj()
                if self.path == "/api/comite":
                    from . import comite
                    resumen = comite.reunir(mesa, ahora)["resumen"]
                    al.commit()
                    return self._json({"ok": True, "resumen": resumen})
                if datos.get("accion") == "parar":
                    mesa.riesgos.activar_kill(ahora, "parada desde el panel")
                elif datos.get("accion") == "reanudar":
                    mesa.riesgos.reactivar(ahora, mesa.equity_fondo())
                else:
                    return self._json({"error": "acción desconocida"}, 400)
                al.commit()                      # guardado antes de responder: el panel vuelve a preguntar al instante
                self._json({"ok": True})
            except Exception as e:
                self._json({"error": str(e)}, 500)
            finally:
                if al is not None:
                    al.cerrar()

    return Manejador


def arrancar(cfg: dict, reloj=None, en_hilo: bool = True, puerto: int | None = None):
    """Levanta el panel. En casa solo escucha en este ordenador. Si el entorno da un PORT (nube) escucha hacia fuera,
    y entonces exige contraseña: un panel abierto a internet dejaría a cualquiera parar el fondo."""
    reloj = reloj or (lambda: pd.Timestamp.now(tz="UTC").floor("s"))
    nube = os.environ.get("PORT", "").isdigit()
    puerto = puerto or (int(os.environ["PORT"]) if nube else cfg["panel"]["puerto"])
    host = cfg["panel"].get("host") or ("0.0.0.0" if nube else "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        clave = clave_panel(cfg)
        if clave is None or len(clave) < 10:
            print("PANEL APAGADO: para abrirlo fuera de este ordenador hace falta una contraseña de al menos 10 caracteres "
                  "en la variable FONDO_CLAVE_PANEL. El fondo sigue funcionando sin panel.", flush=True)
            return None
    servidor = ThreadingHTTPServer((host, puerto), _manejador(cfg, reloj))
    if en_hilo:
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
    else:
        servidor.serve_forever()
    return servidor
