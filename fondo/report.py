"""Informe HTML de una ronda de minería: veredicto, embudo, supervivientes y dónde cae el resto."""
from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from .robustness import ETIQUETAS

CSS = """
:root{--bg:#fcfcfb;--panel:#f3f2ef;--ink:#0b0b0b;--ink2:#52514e;--line:#dddbd5;--serie:#2a78d6;--barra:#9ec5f4;--ok:#0a7a0a;--mal:#b42b2b}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a19;--panel:#262624;--ink:#fff;--ink2:#c3c2b7;--line:#3a3a37;--serie:#3987e5;--barra:#1c5cab;--ok:#4cc24c;--mal:#e66767}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:40px 0 12px}
.sub{color:var(--ink2);margin:0 0 24px}.veredicto{background:var(--panel);border-left:4px solid var(--serie);padding:14px 16px;border-radius:6px;font-size:16px}
.tabla{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--ink2);font-weight:600;font-size:13px}th:first-child,td:first-child,td.t,th.t{text-align:left}
.embudo td:nth-child(3){width:55%}.barra{height:14px;background:var(--barra);border-radius:0 4px 4px 0;min-width:2px}
.tarjetas{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.tarjeta{background:var(--panel);border-radius:8px;padding:14px}.tarjeta h3{margin:0;font-size:15px}.tarjeta p{margin:2px 0 8px;color:var(--ink2);font-size:13px}
svg{display:block;width:100%;height:auto;overflow:visible}.eje{stroke:var(--line);stroke-width:1}.corte{stroke:var(--ink2);stroke-width:1;stroke-dasharray:3 3}
.curva{fill:none;stroke:var(--serie);stroke-width:2;stroke-linejoin:round}.rot{fill:var(--ink2);font-size:11px}
.cursor{stroke:var(--ink2);stroke-width:1;visibility:hidden}.punto{fill:var(--serie);stroke:var(--panel);stroke-width:2;visibility:hidden}
.lectura{font-size:12px;color:var(--ink2);height:18px}.nota{color:var(--ink2);font-size:13px}
"""

JS = """
document.querySelectorAll('.tarjeta').forEach(t=>{const svg=t.querySelector('svg');if(!svg)return;
const d=JSON.parse(svg.dataset.curva),c=JSON.parse(svg.dataset.cortes),W=300,H=110,mn=Math.min(...d,1),mx=Math.max(...d,1),
cur=svg.querySelector('.cursor'),pt=svg.querySelector('.punto'),out=t.querySelector('.lectura');
svg.addEventListener('pointermove',e=>{const r=svg.getBoundingClientRect(),i=Math.max(0,Math.min(d.length-1,Math.round((e.clientX-r.left)/r.width*(d.length-1)))),
x=i/(d.length-1)*W,y=H-(d[i]-mn)/(mx-mn||1)*H;cur.setAttribute('x1',x);cur.setAttribute('x2',x);pt.setAttribute('cx',x);pt.setAttribute('cy',y);
cur.style.visibility=pt.style.visibility='visible';out.textContent=(i<c[0]?'Entrenamiento':i<c[1]?'Validación':'Reserva')+' · capital x'+d[i].toFixed(3);});
svg.addEventListener('pointerleave',()=>{cur.style.visibility=pt.style.visibility='hidden';out.textContent='';});});
"""


def _pct(x) -> str:
    return "—" if x is None else f"{x:+.1%}"


def _num(x, d=2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def _sim(x: dict) -> str:
    return f"cartera de {len(x['simbolos'])} símbolos" if x.get("simbolos") else x["simbolo"]


def _svg(curva: list[float], cortes: list[int]) -> str:
    w, h = 300, 110
    mn, mx = min(min(curva), 1.0), max(max(curva), 1.0)
    esc = lambda v: h - (v - mn) / ((mx - mn) or 1) * h
    n = len(curva) - 1 or 1
    pts = " ".join(f"{i / n * w:.1f},{esc(v):.1f}" for i, v in enumerate(curva))
    marcas = "".join(f'<line class="corte" x1="{c / n * w:.1f}" x2="{c / n * w:.1f}" y1="0" y2="{h}"/>' for c in cortes if c <= n)
    rot = [("Entrenamiento", 0)] + [(t, c / n * w) for t, c in zip(("Validación", "Reserva"), cortes) if c <= n]
    textos = "".join(f'<text class="rot" x="{x + 3:.1f}" y="{h + 14}">{t}</text>' for t, x in rot)
    return (f'<svg viewBox="0 -4 {w} {h + 22}" data-curva="{html.escape(json.dumps(curva))}" data-cortes="{json.dumps(cortes)}" role="img" '
            f'aria-label="Curva de capital, termina en x{curva[-1]:.2f}">'
            f'<line class="eje" x1="0" x2="{w}" y1="{esc(1.0):.1f}" y2="{esc(1.0):.1f}"/>{marcas}'
            f'<polyline class="curva" points="{pts}"/><line class="cursor" y1="0" y2="{h}"/><circle class="punto" r="4"/>{textos}</svg>')


def generar(resultado: dict, cfg: dict, ruta: str | Path, titulo: str = "Informe de minería") -> Path:
    res = resultado["resultados"]
    vivos = sorted((x for x in res if x["sobrevive"]), key=lambda x: -x["reserva"]["sharpe"])
    tope = max(v for _, v in resultado["embudo"][1:]) or 1
    p = [f"<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{html.escape(titulo)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{html.escape(titulo)}</h1><p class='sub'>{html.escape(resultado.get('fecha', ''))} · {len(cfg['simbolos'])} símbolos · "
         f"{', '.join(cfg['timeframes'])} · costes {cfg['costes']['comision'] + cfg['costes']['slippage']:.3%} por lado</p>",
         f"<div class='veredicto'>{html.escape(resultado['veredicto'])}</div>"]

    p.append("<h2>Embudo</h2><div class='tabla'><table class='embudo'><tr><th>Etapa</th><th>Quedan</th><th class='t'></th></tr>")
    for i, (etapa, n) in enumerate(resultado["embudo"]):
        barra = "" if i == 0 else f"<div class='barra' style='width:{n / tope * 100:.1f}%'></div>"
        miles = f"{n:,}".replace(",", ".")
        p.append(f"<tr><td>{html.escape(etapa.replace('_', ' ').capitalize())}</td><td>{miles}</td><td class='t'>{barra}</td></tr>")
    if resultado.get("placebo"):
        p.append(f"<tr><td>Hallazgos distintos</td><td>{resultado.get('hallazgos', '')}</td><td class='t'></td></tr>")
        p.append(f"<tr><td>Hallazgos en ruido puro, por ronda</td><td>{', '.join(map(str, resultado['placebo']))}</td><td class='t'></td></tr>")
    p.append("</table></div><p class='nota'>El control de ruido repite todo el proceso sobre los mismos datos con la dirección de cada vela "
             "invertida al azar alrededor de su subida media. Lo que sobrevive ahí es suerte, o simplemente haber estado comprado en un mercado "
             "que subía. Solo cuenta como hallazgo real lo que casi ninguna ronda de ruido iguala.</p>")

    p.append(f"<h2>Supervivientes ({len(vivos)})</h2>")
    if vivos:
        p.append("<div class='tabla'><table><tr><th>Estrategia</th><th class='t'>Parámetros</th><th>Sharpe entr.</th><th>Sharpe valid.</th>"
                 "<th>Sharpe reserva</th><th>Retorno reserva</th><th>Caída máx. reserva</th><th>Operaciones</th><th>DSR</th></tr>")
        for x in vivos:
            pr = ", ".join(f"{k}={v}" for k, v in x["params"].items())
            p.append(f"<tr><td>{x['nombre']} · {_sim(x)} · {x['tf']}</td><td class='t'>{html.escape(pr)}</td>"
                     f"<td>{_num(x['entrenamiento']['sharpe'])}</td><td>{_num(x['validacion']['sharpe'])}</td><td>{_num(x['reserva']['sharpe'])}</td>"
                     f"<td>{_pct(x['reserva']['retorno'])}</td><td>{_pct(-x['reserva']['dd_max'])}</td>"
                     f"<td>{x['entrenamiento']['trades'] + x['validacion']['trades'] + x['reserva']['trades']}</td><td>{_num(x['dsr'])}</td></tr>")
        p.append("</table></div><p class='nota'>DSR: probabilidad de que el Sharpe de entrenamiento no sea fruto de haber probado tantas combinaciones "
                 "(cálculo teórico, muy exigente). Por debajo de 0,9 no hay prueba estadística sólida.</p><div class='tarjetas'>")
        for x in vivos:
            p.append(f"<div class='tarjeta'><h3>{x['nombre']} · {_sim(x)} · {x['tf']}</h3><p>Capital x{x['curva'][-1]:.2f} en todo el histórico, costes incluidos</p>"
                     f"{_svg(x['curva'], x['cortes'])}<div class='lectura'></div></div>")
        p.append("</div>")
    else:
        p.append("<p>Ninguna. Es el resultado normal cuando no hay ventaja: no relajes los filtros hasta que salga algo.</p>")

    caidas = Counter(x["caida_en"] for x in res if not x["sobrevive"])
    if caidas:
        p.append("<h2>Dónde caen las demás</h2><div class='tabla'><table><tr><th>Filtro</th><th>Descartadas</th></tr>")
        for f, n in caidas.most_common():
            p.append(f"<tr><td>{html.escape(ETIQUETAS.get(f, str(f)).capitalize())}</td><td>{n}</td></tr>")
        p.append("</table></div>")

    p.append(f"<p class='nota'>Resultados simulados sobre datos históricos. No garantizan nada sobre el futuro.</p></main><script>{JS}</script></body></html>")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("".join(p), encoding="utf-8")
    return ruta
