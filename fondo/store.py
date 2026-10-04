"""Persistencia en SQLite: estrategias, cuentas de papel, órdenes, curva de capital y eventos."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

ESQUEMA = """
CREATE TABLE IF NOT EXISTS estrategias (
    id INTEGER PRIMARY KEY, simbolo TEXT, tf TEXT, nombre TEXT, params TEXT,
    estado TEXT, metricas TEXT, creado TEXT, actualizado TEXT,
    UNIQUE (simbolo, tf, nombre, params)
);
CREATE TABLE IF NOT EXISTS cuentas (
    estrategia_id INTEGER PRIMARY KEY, fase TEXT, equity REAL, nav REAL, pico REAL,
    pos REAL, sig REAL, tam REAL, precio REAL, ts_marca TEXT, ultima_vela TEXT,
    trades INTEGER, alta TEXT, motivo TEXT, nav_entrada REAL, racha INTEGER DEFAULT 0, pausa_hasta TEXT
);
-- para estrategias guarda el nav; para el fondo (estrategia_id 0) guarda el capital total
CREATE TABLE IF NOT EXISTS equity (ts TEXT, estrategia_id INTEGER, equity REAL);
CREATE INDEX IF NOT EXISTS equity_idx ON equity (estrategia_id, ts);
CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY, ts TEXT, estrategia_id INTEGER, simbolo TEXT,
    pos_antes REAL, pos_despues REAL, precio REAL, coste REAL, motivo TEXT
);
CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, ts TEXT, origen TEXT, tipo TEXT, mensaje TEXT, datos TEXT);
CREATE TABLE IF NOT EXISTS kv (clave TEXT PRIMARY KEY, valor TEXT);
"""

FONDO = 0  # estrategia_id reservado para la curva del fondo en la tabla equity


class Almacen:
    def __init__(self, ruta: str | Path = "fondo.db"):
        self.db = sqlite3.connect(str(ruta), timeout=30)     # la mesa, el panel y la minería comparten la base
        self.db.row_factory = sqlite3.Row
        if str(ruta) != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(ESQUEMA)
        tengo = {f["name"] for f in self.db.execute("PRAGMA table_info(cuentas)")}       # bases creadas con versiones anteriores
        for col, tipo in (("nav_entrada", "REAL"), ("racha", "INTEGER DEFAULT 0"), ("pausa_hasta", "TEXT")):
            if col not in tengo:
                try:
                    self.db.execute(f"ALTER TABLE cuentas ADD COLUMN {col} {tipo}")
                except sqlite3.OperationalError:      # otro proceso la añadió a la vez
                    pass

    def cerrar(self):
        self.db.commit()
        self.db.close()

    # ------------------------------------------------------------ clave-valor
    def get(self, clave: str, defecto=None):
        f = self.db.execute("SELECT valor FROM kv WHERE clave=?", (clave,)).fetchone()
        return json.loads(f["valor"]) if f else defecto

    def set(self, clave: str, valor):
        self.db.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, json.dumps(valor)))

    # ------------------------------------------------------------ estrategias
    def alta_estrategia(self, simbolo, tf, nombre, params: dict, estado: str, metricas: dict, ts) -> int | None:
        """Devuelve el id nuevo, o None si esa estrategia ya existía."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO estrategias (simbolo, tf, nombre, params, estado, metricas, creado, actualizado) VALUES (?,?,?,?,?,?,?,?)",
            (simbolo, tf, nombre, json.dumps(params, sort_keys=True), estado, json.dumps(metricas), str(ts), str(ts)))
        return cur.lastrowid if cur.rowcount else None

    def estrategias(self, estados: tuple[str, ...] | None = None) -> list[dict]:
        q = "SELECT * FROM estrategias"
        if estados:
            q += f" WHERE estado IN ({','.join('?' * len(estados))})"
        out = []
        for f in self.db.execute(q + " ORDER BY id", estados or ()):
            d = dict(f)
            d["params"], d["metricas"] = json.loads(d["params"]), json.loads(d["metricas"] or "{}")
            out.append(d)
        return out

    def estado_estrategia(self, eid: int, estado: str, ts):
        self.db.execute("UPDATE estrategias SET estado=?, actualizado=? WHERE id=?", (estado, str(ts), eid))

    # ------------------------------------------------------------ cuentas
    def cuenta(self, eid: int) -> dict | None:
        f = self.db.execute("SELECT * FROM cuentas WHERE estrategia_id=?", (eid,)).fetchone()
        return dict(f) if f else None

    def guardar_cuenta(self, c: dict):
        cols = list(c)
        self.db.execute(f"INSERT OR REPLACE INTO cuentas ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [c[k] for k in cols])

    def nueva_cuenta(self, eid: int, fase: str, capital: float, ts) -> dict:
        # equity = dinero asignado; nav = índice de rendimiento (1.0 al empezar), no le afectan los cambios de capital
        c = {"estrategia_id": eid, "fase": fase, "equity": capital, "nav": 1.0, "pico": 1.0,
             "pos": 0.0, "sig": 0.0, "tam": 0.0, "precio": None, "ts_marca": None, "ultima_vela": None,
             "trades": 0, "alta": str(ts), "motivo": None, "nav_entrada": None, "racha": 0, "pausa_hasta": None}
        self.guardar_cuenta(c)
        return c

    # ------------------------------------------------------------ series y registro
    def apuntar_equity(self, ts, eid: int, equity: float):
        self.db.execute("INSERT INTO equity VALUES (?,?,?)", (str(ts), eid, equity))

    def curva(self, eid: int, desde=None) -> pd.Series:
        q, args = "SELECT ts, equity FROM equity WHERE estrategia_id=?", [eid]
        if desde:
            q += " AND ts>=?"
            args.append(str(desde))
        filas = self.db.execute(q + " ORDER BY ts", args).fetchall()
        if not filas:
            return pd.Series(dtype=float)
        return pd.Series([f["equity"] for f in filas], index=pd.to_datetime([f["ts"] for f in filas], utc=True))

    def orden(self, ts, eid, simbolo, pos_antes, pos_despues, precio, coste, motivo):
        self.db.execute("INSERT INTO ordenes (ts, estrategia_id, simbolo, pos_antes, pos_despues, precio, coste, motivo) VALUES (?,?,?,?,?,?,?,?)",
                        (str(ts), eid, simbolo, pos_antes, pos_despues, precio, coste, motivo))

    def evento(self, ts, origen: str, tipo: str, mensaje: str, datos: dict | None = None):
        self.db.execute("INSERT INTO eventos (ts, origen, tipo, mensaje, datos) VALUES (?,?,?,?,?)",
                        (str(ts), origen, tipo, mensaje, json.dumps(datos or {})))

    def contar(self, estado: str) -> int:
        return self.db.execute("SELECT count(*) FROM estrategias WHERE estado=?", (estado,)).fetchone()[0]

    def eventos(self, n: int = 30) -> list[dict]:
        return [dict(f) for f in self.db.execute("SELECT * FROM eventos ORDER BY id DESC LIMIT ?", (n,))][::-1]

    def commit(self):
        self.db.commit()
