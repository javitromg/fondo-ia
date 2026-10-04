// Oficina 3D del fondo. Nada es decorado suelto: cada persona sentada en la sala de trading es una estrategia de
// /api/estado, su pantalla enseña la posición que tiene abierta, cada despacho es un departamento que ya ha
// trabajado y los bocadillos son eventos reales. El panel la usa si el navegador tiene WebGL; si no, queda el plano.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/addons/BufferGeometryUtils.js';

const PIEL = ['#f3d0b1', '#e6b58c', '#cf9668', '#a8734a', '#7a5236', '#f0c4a0'];
const PELO = ['#1b1917', '#33241a', '#5e4126', '#8f6a3c', '#c8c0b4', '#6e2c1c', '#2a2f3a'];
const CAMISAS = ['#f3f2ee', '#dde6f1', '#c5d5ea', '#ece4d5', '#b8c8d8', '#e8dfe6', '#cfe0d6'];
const SUDADERAS = ['#56799f', '#5f8a74', '#86689a', '#a1765a', '#4c6877', '#7b8858', '#a05f5f', '#3f5a85', '#b08a3c'];
const PANTALON = ['#27323a', '#3a3f4a', '#4a4238', '#2f3a55', '#55504a'];

const N = 10, DW = 1.3, DD = 0.75, X0 = 2.0, PASILLO = 16.9, HIP_SENTADO = 0.52, HIP_PIE = 0.86;
const COL = [18.8, 24.9, 29.8], ANCHO_COL = [5.5, 4.3, 4.3];
// despachos en huecos fijos: aparecen cuando el departamento ha hecho ya algo
const SALAS = [
  { id: 'rie', nombre: 'Riesgos', col: 0, z: 0.5, d: 4.7, clase: 'riesgos', gente: ['rie'] },
  { id: 'com', nombre: 'Comité', col: 0, z: 5.7, d: 5.3, clase: 'comite', gente: ['com'] },
  { id: 'lab', nombre: 'Laboratorio', col: 0, z: 11.5, d: 5.9, clase: 'laboratorio', gente: ['lab', 'lab2'] },
  { id: 'ana', nombre: 'Debate', col: 0, z: 17.9, d: 4.8, clase: 'debate', gente: ['alc', 'baj', 'mod'], zona: 'Moderador' },
  { id: 'aud', nombre: 'Auditoría', col: 1, z: 0.5, d: 3.6, gente: ['aud'], zona: 'Auditoría' },
  { id: 'car', nombre: 'Cartera', col: 1, z: 4.5, d: 3.6, gente: ['car'], zona: 'Cartera' },
  { id: 'sel', nombre: 'Selección', col: 1, z: 8.5, d: 3.6, gente: ['sel'], zona: 'Selección' },
  { id: 'inv', nombre: 'Investigación', col: 1, z: 12.5, d: 3.6, gente: ['inv'], zona: 'Investigación' },
  { id: 'mac', nombre: 'Macro', col: 1, z: 16.5, d: 3.6, gente: ['mac'], zona: 'Macro' },
  { id: 'dat', nombre: 'Datos', col: 2, z: 0.5, d: 3.6, gente: ['dat'], zona: 'Datos' },
  { id: 'eje', nombre: 'Ejecución', col: 2, z: 4.5, d: 3.6, gente: ['eje'], zona: 'Ejecución' },
  { id: 'ope', nombre: 'Operaciones', col: 2, z: 8.5, d: 3.6, gente: ['ope'], zona: 'Operaciones' },
  { id: 'not', nombre: 'Noticias', col: 2, z: 12.5, d: 3.6, gente: ['not'], zona: 'Noticias' },
  { id: 'sen', nombre: 'Sentimiento', col: 2, z: 16.5, d: 3.6, gente: ['sen'], zona: 'Sentimiento' },
];

function azar(semilla) {                                  // generador con semilla: cada persona es siempre la misma
  let a = (semilla * 2654435761) >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const M = (x, y, z, ry = 0, sx = 1, sy = 1, sz = 1, rx = 0) =>
  new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, 0, 'YXZ')), new THREE.Vector3(sx, sy, sz));

// ------------------------------------------------------------------ geometrías compartidas
const G = {
  caja: new THREE.BoxGeometry(1, 1, 1),
  cil: new THREE.CylinderGeometry(1, 1, 1, 20),
  plano: new THREE.PlaneGeometry(1, 1),
  asiento: new RoundedBoxGeometry(0.46, 0.07, 0.46, 2, 0.03),
  respaldo: new RoundedBoxGeometry(0.42, 0.5, 0.05, 2, 0.025),
  torso: new THREE.CapsuleGeometry(0.14, 0.3, 4, 12),
  cadera: new RoundedBoxGeometry(0.31, 0.17, 0.22, 2, 0.07),
  cuello: new THREE.CylinderGeometry(0.045, 0.05, 0.09, 10),
  cabeza: new THREE.SphereGeometry(0.115, 16, 12),
  ojo: new THREE.SphereGeometry(0.012, 6, 4),
  casco: new THREE.SphereGeometry(0.124, 16, 8, 0, Math.PI * 2, 0, Math.PI * 0.54),
  rapado: new THREE.SphereGeometry(0.119, 16, 6, 0, Math.PI * 2, 0, Math.PI * 0.42),
  melena: new RoundedBoxGeometry(0.21, 0.27, 0.09, 2, 0.04),
  mono: new THREE.SphereGeometry(0.052, 8, 6),
  brazo: new THREE.CapsuleGeometry(0.046, 0.2, 3, 8),
  antebrazo: new THREE.CapsuleGeometry(0.039, 0.18, 3, 8),
  mano: new THREE.SphereGeometry(0.044, 8, 6),
  muslo: new THREE.CapsuleGeometry(0.07, 0.26, 3, 8),
  pierna: new THREE.CapsuleGeometry(0.054, 0.28, 3, 8),
  zapato: new RoundedBoxGeometry(0.095, 0.07, 0.23, 2, 0.03),
  hoja: new THREE.IcosahedronGeometry(1, 1),
  estrella: (() => { const s = new THREE.Shape(); for (let i = 0; i < 10; i++) { const r = i % 2 ? 0.045 : 0.11, a = -Math.PI / 2 + i * Math.PI / 5; s[i ? 'lineTo' : 'moveTo'](r * Math.cos(a), -r * Math.sin(a)); } return new THREE.ExtrudeGeometry(s, { depth: 0.03, bevelEnabled: false }); })(),
  anillo: new THREE.RingGeometry(0.42, 0.5, 40),
};

function pieza(geo, color, m) {                           // copia de una geometría, colocada y pintada de un color (para fundir varias en una malla)
  const g = geo.index ? geo.toNonIndexed() : geo.clone();
  if (m) g.applyMatrix4(m);
  const c = new THREE.Color(color), n = g.attributes.position.count, a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { a[i * 3] = c.r; a[i * 3 + 1] = c.g; a[i * 3 + 2] = c.b; }
  g.setAttribute('color', new THREE.BufferAttribute(a, 3));
  for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv', 'color'].includes(k)) g.deleteAttribute(k);
  return g;
}
const fundir = piezas => { const g = mergeGeometries(piezas); piezas.forEach(p => p.dispose()); return g; };

class Lote {                                              // muebles repetidos: una sola malla instanciada por tipo
  constructor() { this.m = new Map(); }
  pon(clave, geo, mat, matriz) { let e = this.m.get(clave); if (!e) this.m.set(clave, e = { geo, mat, ms: [] }); e.ms.push(matriz); }
  volcar(grupo) {
    for (const e of this.m.values()) {
      const im = new THREE.InstancedMesh(e.geo, e.mat, e.ms.length);
      e.ms.forEach((m, i) => im.setMatrixAt(i, m));
      im.castShadow = im.receiveShadow = true;
      grupo.add(im);
    }
  }
}

function lienzo(w, h, pintar) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  t.repintar = f => { f(c.getContext('2d'), w, h); t.needsUpdate = true; };
  if (pintar) t.repintar(pintar);
  return t;
}
const FUENTE = 'Archivo, system-ui, "Segoe UI", sans-serif';

export function crear(marco, op) {
  const quieto = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const oscuroMQ = matchMedia('(prefers-color-scheme: dark)');
  const css = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.shadowMap.autoUpdate = false;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const tela = renderer.domElement;
  tela.setAttribute('role', 'img');
  tela.setAttribute('aria-label', 'Oficina del fondo en 3D: cada persona de la sala de trading es una estrategia. El detalle está en las tablas de abajo.');
  marco.appendChild(tela);

  const escena = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  escena.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const camara = new THREE.PerspectiveCamera(30, 16 / 9, 0.5, 220);
  const control = new OrbitControls(camara, tela);
  control.enableDamping = true; control.dampingFactor = 0.09; control.enableZoom = false;
  control.minPolarAngle = 0.3; control.maxPolarAngle = 1.36; control.screenSpacePanning = false;
  control.rotateSpeed = 0.55; control.panSpeed = 0.7;
  tela.style.touchAction = 'pan-y';                       // en el móvil el dedo en vertical sigue desplazando la página

  const hemi = new THREE.HemisphereLight(0xffffff, 0x8c8f86, 0.9);
  const sol = new THREE.DirectionalLight(0xfff2dc, 2.2);
  sol.castShadow = true; sol.shadow.mapSize.set(2048, 2048); sol.shadow.bias = -0.0004; sol.shadow.normalBias = 0.03; sol.shadow.radius = 5;
  escena.add(hemi, sol, sol.target);

  // ---------------------------------------------------------------- materiales
  const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0, ...o });
  const MAT = {
    gente: std('#ffffff', { vertexColors: true, roughness: 0.78 }),
    madera: std('#b89163', { roughness: 0.55 }), metal: std('#39464f', { roughness: 0.45, metalness: 0.5 }), silla: std('#252e35', { roughness: 0.7 }),
    tela: std('#7d8b90', { roughness: 0.95 }), monitor: std('#151b20', { roughness: 0.35, metalness: 0.3 }), tecla: std('#20272c', { roughness: 0.6 }),
    laton: std('#b6923f', { roughness: 0.32, metalness: 0.85 }), vidrio: std('#bfe3ea', { transparent: true, opacity: 0.28, roughness: 0.08, metalness: 0.1, depthWrite: false }),
    pared: std('#eef0ec', { roughness: 0.95 }), losa: std('#c9cfcc', { roughness: 0.9 }), suelo: std('#dfe3e0', { roughness: 0.96 }),
    alfMesa: std('#d9c99b', { roughness: 1 }), alfInc: std('#b4c9e2', { roughness: 1 }), maceta: std('#e9e4da', { roughness: 0.6 }), hoja: std('#3f7d4d', { roughness: 0.85 }),
    taza: std('#c9553d', { roughness: 0.4 }), rack: std('#2a333a', { roughness: 0.5, metalness: 0.4 }), blanco: std('#f6f6f2', { roughness: 0.5 }), lampara: std('#fff4d6', { emissive: '#ffe7b0', emissiveIntensity: 1.3 }),
    anillo: new THREE.MeshBasicMaterial({ color: '#b6923f', side: THREE.DoubleSide, transparent: true, opacity: 0.95 }),
  };
  function pantallaTex(estado) {
    return lienzo(160, 96, (c, w, h) => {
      const fondo = { largo: '#0d2a18', corto: '#2c1012', fuera: '#12191e', pausa: '#2b2108' }[estado], tinta = { largo: '#58d67c', corto: '#f07a7a', fuera: '#31414b', pausa: '#e9b24c' }[estado];
      c.fillStyle = fondo; c.fillRect(0, 0, w, h);
      c.strokeStyle = tinta; c.lineWidth = 3; c.globalAlpha = estado === 'fuera' ? 0.5 : 0.75; c.beginPath();
      const r = azar({ largo: 3, corto: 7, fuera: 11, pausa: 5 }[estado]);
      for (let i = 0; i <= 12; i++) { const y = estado === 'largo' ? 70 - i * 3.6 : estado === 'corto' ? 26 + i * 3.6 : 48; c[i ? 'lineTo' : 'moveTo'](8 + i * 7, y + (r() - 0.5) * 16); }
      c.stroke(); c.globalAlpha = 1; c.fillStyle = tinta;
      if (estado === 'largo') { c.beginPath(); c.moveTo(128, 22); c.lineTo(150, 62); c.lineTo(106, 62); c.fill(); }
      if (estado === 'corto') { c.beginPath(); c.moveTo(128, 74); c.lineTo(150, 34); c.lineTo(106, 34); c.fill(); }
      if (estado === 'pausa') { c.fillRect(112, 30, 11, 38); c.fillRect(133, 30, 11, 38); }
    });
  }
  const PANT = {};
  for (const k of ['largo', 'corto', 'fuera', 'pausa']) { const t = pantallaTex(k); PANT[k] = new THREE.MeshStandardMaterial({ color: '#000000', emissive: '#ffffff', emissiveMap: t, emissiveIntensity: k === 'fuera' ? 0.5 : 1.25, roughness: 0.3 }); }

  const LUZ = { largo: std('#0d2a18', { emissive: '#38d06a', emissiveIntensity: 2.2 }), corto: std('#2c1012', { emissive: '#ff5a5a', emissiveIntensity: 2.2 }),
                fuera: std('#2a3338', { roughness: 0.5 }), pausa: std('#2b2108', { emissive: '#f0b030', emissiveIntensity: 2.0 }) };
  const ponPantalla = (a, k) => { if (a.pantalla) { a.pantalla.material = PANT[k]; a.pantalla.userData.luz.material = LUZ[k]; } };

  // ---------------------------------------------------------------- estado
  let e = null, primera = true, firma = '', W = 35, D = 24, activos = new Set(), seleccion = null, encima = null, vistoEv = null;
  let cola = [], globos = [], distObjetivo = 40, sombras = 0, visible = true, ultimo = performance.now(), ultimoCuadro = 0;
  const mobiliario = new THREE.Group(), gentes = new THREE.Group();
  escena.add(mobiliario, gentes);
  const personas = new Map();                              // 'b12' (bot) o 'p-rie' (personal) -> persona
  let asientos = { aprobada: [], incubadora: [] }, puestos = {}, racks = [], puertaLab = [PASILLO, 14], zonas = {};
  const texMuro = lienzo(1536, 384), texRiesgos = lienzo(768, 256), texCielo = lienzo(2048, 256);
  const anillo = new THREE.Mesh(G.anillo, MAT.anillo); anillo.rotation.x = -Math.PI / 2; anillo.visible = false; escena.add(anillo);
  const estrella = new THREE.Mesh(G.estrella, MAT.laton); estrella.visible = false; escena.add(estrella);
  const rotulo = document.createElement('div'); rotulo.className = 'rotulo'; rotulo.hidden = true; marco.appendChild(rotulo);

  // ---------------------------------------------------------------- personas
  function crearPersona(clave, semilla, camisa, nombre) {
    const r = azar(semilla + 17), elige = xs => xs[Math.floor(r() * xs.length)];
    const piel = elige(PIEL), pelo = elige(PELO), estilo = Math.floor(r() * 4), pantalon = elige(PANTALON), manga = r() < 0.35 ? piel : camisa;
    const ancho = 0.93 + r() * 0.16, talla = 0.95 + r() * 0.09;
    const raiz = new THREE.Group(), cuerpo = new THREE.Group(), tronco = new THREE.Group();
    raiz.add(cuerpo); cuerpo.add(tronco); raiz.scale.setScalar(talla);
    const malla = g => { const m = new THREE.Mesh(g, MAT.gente); m.castShadow = true; return m; };
    tronco.add(malla(fundir([pieza(G.cadera, pantalon, M(0, 0.02, 0, 0, ancho)), pieza(G.torso, camisa, M(0, 0.34, 0, 0, 1.12 * ancho, 1, 0.76)), pieza(G.cuello, piel, M(0, 0.68, 0))])));
    const pelos = [pieza(estilo === 3 ? G.rapado : G.casco, pelo, M(0, 0.012, -0.012, 0, 1, 1, 1, -0.28))];
    if (estilo === 1) pelos.push(pieza(G.melena, pelo, M(0, -0.09, -0.085)));
    if (estilo === 2) pelos.push(pieza(G.mono, pelo, M(0, 0.1, -0.1)));
    const cabeza = malla(fundir([pieza(G.cabeza, piel, M(0, 0, 0, 0, 0.93, 1.08, 1)), pieza(G.ojo, '#1c1c1c', M(0.04, 0.012, 0.104)), pieza(G.ojo, '#1c1c1c', M(-0.04, 0.012, 0.104)), ...pelos]));
    cabeza.position.y = 0.82; tronco.add(cabeza);
    const lado = s => {
      const hombro = new THREE.Group(), codo = new THREE.Group(), cadera = new THREE.Group(), rodilla = new THREE.Group();
      hombro.position.set(s * 0.2 * ancho, 0.56, 0); codo.position.y = -0.28;
      hombro.add(malla(pieza(G.brazo, camisa, M(0, -0.14, 0))), codo);
      codo.add(malla(fundir([pieza(G.antebrazo, manga, M(0, -0.12, 0)), pieza(G.mano, piel, M(0, -0.26, 0))])));
      cadera.position.set(s * 0.09 * ancho, 0, 0); rodilla.position.y = -0.4;
      cadera.add(malla(pieza(G.muslo, pantalon, M(0, -0.19, 0))), rodilla);
      rodilla.add(malla(fundir([pieza(G.pierna, pantalon, M(0, -0.19, 0)), pieza(G.zapato, '#22262a', M(0, -0.41, 0.05))])));
      tronco.add(hombro); cuerpo.add(cadera);
      return { hombro, codo, cadera, rodilla };
    };
    const p = { clave, nombre, raiz, cuerpo, tronco, cabeza, izq: lado(1), der: lado(-1), fase: r() * 6.28, pose: 'sentado', activo: false, gesto: 'teclea', ruta: null, asiento: null, talla };
    gentes.add(raiz); personas.set(clave, p);
    return p;
  }
  function pose(p, t) {                                    // coloca brazos, piernas y tronco según lo que hace la persona
    const { izq, der, cuerpo, tronco, cabeza, fase } = p, mov = quieto ? 0 : 1;
    if (p.pose === 'andando') {
      const k = Math.sin(t * 7.5 + fase) * mov;
      cuerpo.position.y = HIP_PIE + Math.abs(Math.cos(t * 7.5 + fase)) * 0.02; tronco.rotation.set(0.05, 0, 0); cabeza.rotation.set(0, 0, 0);
      izq.cadera.rotation.x = -k * 0.55; der.cadera.rotation.x = k * 0.55; izq.rodilla.rotation.x = Math.max(0, k) * 0.7; der.rodilla.rotation.x = Math.max(0, -k) * 0.7;
      izq.hombro.rotation.set(k * 0.5, 0, 0.06); der.hombro.rotation.set(-k * 0.5, 0, -0.06); izq.codo.rotation.x = der.codo.rotation.x = -0.35;
      return;
    }
    const lento = Math.sin(t * 0.5 + fase) * mov;
    if (p.pose === 'de_pie') {
      cuerpo.position.y = HIP_PIE; tronco.rotation.set(0, lento * 0.05, 0); cabeza.rotation.set(0, lento * 0.25, 0);
      for (const l of [izq, der]) { l.cadera.rotation.x = 0; l.rodilla.rotation.x = 0; }
      const habla = p.activo ? Math.max(0, Math.sin(t * 2.2 + fase)) * mov : 0;      // gesticula con una mano
      izq.hombro.rotation.set(-0.15 - habla * 0.7, 0, 0.08); izq.codo.rotation.x = -0.5 - habla * 0.9;
      der.hombro.rotation.set(-0.1, 0, -0.08); der.codo.rotation.x = -0.35;
      return;
    }
    cuerpo.position.y = HIP_SENTADO;
    for (const l of [izq, der]) { l.cadera.rotation.x = -1.5; l.rodilla.rotation.x = 1.48; }
    izq.cadera.rotation.z = 0.07; der.cadera.rotation.z = -0.07;
    if (p.activo) {                                        // trabajando: inclinado sobre el teclado
      const a = Math.sin(t * 9 + fase) * 0.07 * mov, b = Math.cos(t * 7.3 + fase) * 0.07 * mov;
      tronco.rotation.set(0.1, 0, 0); cabeza.rotation.set(0.06, lento * 0.12, 0);
      izq.hombro.rotation.set(-0.5, 0, -0.1); der.hombro.rotation.set(-0.5, 0, 0.1); izq.codo.rotation.x = -1.02 + a; der.codo.rotation.x = -1.02 + b;
    } else {                                               // sin posición: echado hacia atrás, manos en el regazo
      tronco.rotation.set(-0.14, 0, 0); cabeza.rotation.set(0.1, lento * 0.4, 0);
      izq.hombro.rotation.set(-0.05, 0, -0.12); der.hombro.rotation.set(-0.05, 0, 0.12); izq.codo.rotation.x = der.codo.rotation.x = -0.78;
    }
  }
  function colocar(p, a, andando) {                        // sienta (o pone de pie) a la persona en su sitio; si `andando`, va caminando
    const antes = p.asiento; p.asiento = a;
    if (andando && !quieto) {
      const desde = p.raiz.position.clone(), fila = a.z + (Math.abs(a.giro) < 1.6 ? -0.85 : 0.85), pts = [];
      if (antes) pts.push(new THREE.Vector3(desde.x, 0, antes.z + (Math.abs(antes.giro) < 1.6 ? -0.85 : 0.85)));
      pts.push(new THREE.Vector3(PASILLO, 0, pts.length ? pts[pts.length - 1].z : desde.z), new THREE.Vector3(PASILLO, 0, fila), new THREE.Vector3(a.x, 0, fila), new THREE.Vector3(a.x, 0, a.z));
      p.ruta = pts; p.pose = 'andando'; p.alLlegar = () => colocar(p, a, false);
      return;
    }
    p.ruta = null; p.raiz.position.set(a.x, 0, a.z); p.raiz.rotation.y = a.giro; p.pose = a.de_pie ? 'de_pie' : 'sentado';
  }
  function despedir(p) {                                   // se levanta y sale por la puerta del fondo del pasillo
    const z = p.raiz.position.z, fila = p.asiento ? p.asiento.z + (Math.abs(p.asiento.giro) < 1.6 ? -0.85 : 0.85) : z;
    if (quieto) return quitar(p);
    p.ruta = [new THREE.Vector3(p.raiz.position.x, 0, fila), new THREE.Vector3(PASILLO, 0, fila), new THREE.Vector3(PASILLO, 0, D + 1.5)];
    p.pose = 'andando'; p.saliendo = true; p.alLlegar = () => quitar(p);
  }
  function quitar(p) {
    gentes.remove(p.raiz); personas.delete(p.clave);
    p.raiz.traverse(o => { if (o.isMesh) o.geometry.dispose(); });
    if (seleccion === p.clave) seleccion = null;
  }

  // ---------------------------------------------------------------- oficina
  function cartel(texto, ancho, alto, color, fondo) {
    const t = lienzo(512, Math.max(32, Math.round(512 * alto / ancho)), (c, w, h) => {
      if (fondo) { c.fillStyle = fondo; c.fillRect(0, 0, w, h); }
      c.fillStyle = color; c.textAlign = 'center'; c.textBaseline = 'middle';
      let px = h * 0.6; c.font = `600 ${px}px ${FUENTE}`;
      while (c.measureText(texto).width > w * 0.88 && px > 10) { px -= 2; c.font = `600 ${px}px ${FUENTE}`; }
      c.fillText(texto, w / 2, h / 2 + px * 0.05);
    });
    const m = new THREE.Mesh(G.plano, new THREE.MeshBasicMaterial({ map: t, transparent: !fondo }));
    m.scale.set(ancho, alto, 1);
    return m;
  }
  function puesto(lote, grupo, x, z, giro, conMonitor = true) {   // silla + mesa + pantalla, mirando hacia `giro`
    const base = M(x, 0, z, giro), pon = (k, geo, mat, m) => lote.pon(k, geo, mat, base.clone().multiply(m));
    pon('asiento', G.asiento, MAT.silla, M(0, 0.42, -0.02)); pon('respaldo', G.respaldo, MAT.silla, M(0, 0.74, -0.25, 0, 1, 1, 1, -0.1));
    pon('pie', G.cil, MAT.metal, M(0, 0.22, -0.02, 0, 0.03, 0.36, 0.03)); pon('base', G.cil, MAT.metal, M(0, 0.04, -0.02, 0, 0.27, 0.035, 0.27));
    const zc = 0.3 + DD / 2;
    pon('tablero', G.caja, MAT.madera, M(0, 0.73, zc, 0, DW - 0.04, 0.04, DD));
    pon('pata', G.caja, MAT.metal, M(DW / 2 - 0.05, 0.355, zc, 0, 0.035, 0.71, DD - 0.1)); pon('pata', G.caja, MAT.metal, M(-DW / 2 + 0.05, 0.355, zc, 0, 0.035, 0.71, DD - 0.1));
    pon('tecla', G.caja, MAT.tecla, M(0, 0.76, 0.47, 0, 0.38, 0.016, 0.13));
    const r = azar(Math.round(x * 97 + z * 131));
    if (r() < 0.55) pon('taza', G.cil, MAT.taza, M(0.36 + r() * 0.12, 0.795, 0.5 + r() * 0.2, 0, 0.038, 0.09, 0.038));
    if (r() < 0.45) pon('libreta', G.caja, MAT.blanco, M(-0.4 - r() * 0.1, 0.757, 0.52 + r() * 0.15, r() - 0.5, 0.16, 0.012, 0.22));
    if (!conMonitor) return null;
    const zm = 0.3 + DD - 0.17;
    pon('monitor', G.caja, MAT.monitor, M(0, 1.07, zm, 0, 0.62, 0.37, 0.03)); pon('soporte', G.caja, MAT.monitor, M(0, 0.86, zm + 0.02, 0, 0.05, 0.22, 0.04));
    pon('peana', G.caja, MAT.monitor, M(0, 0.757, zm + 0.02, 0, 0.24, 0.014, 0.16));
    const pantalla = new THREE.Mesh(G.plano, PANT.fuera);
    pantalla.applyMatrix4(base.clone().multiply(M(0, 1.07, zm - 0.017, Math.PI, 0.57, 0.32, 1)));
    const luz = new THREE.Mesh(G.caja, LUZ.fuera);          // testigo encima del monitor: se ve desde cualquier lado
    luz.applyMatrix4(base.clone().multiply(M(0, 1.275, zm, 0, 0.5, 0.035, 0.05)));
    grupo.add(pantalla, luz);
    pantalla.userData.luz = luz;
    return pantalla;
  }
  function planta(lote, x, z, s = 1) {
    lote.pon('maceta', G.cil, MAT.maceta, M(x, 0.22 * s, z, 0, 0.2 * s, 0.44 * s, 0.2 * s));
    [[0, 0.78, 0, 0.36], [0.16, 1.02, 0.08, 0.27], [-0.14, 1.1, -0.1, 0.25], [0.02, 1.32, 0.02, 0.2]].forEach(([dx, y, dz, r]) => lote.pon('hoja', G.hoja, MAT.hoja, M(x + dx * s, y * s, z + dz * s, dx * 9, r * s, r * 1.15 * s, r * s)));
  }

  function construir() {                                   // levanta la oficina a la medida de la plantilla y de los departamentos activos
    mobiliario.traverse(o => { if (o.isInstancedMesh) o.dispose(); if (o.isMesh && o.material && o.material.map && o.userData.propio) { o.material.map.dispose(); o.material.dispose(); } });
    mobiliario.clear(); racks = []; puestos = {}; zonas = {};
    const nF = e ? e.estrategias.filter(x => x.estado === 'aprobada').length : 0, nI = e ? e.estrategias.length - nF : 0;
    const fF = Math.min(3, Math.max(1, Math.ceil(nF / (2 * N)))), fI = Math.min(6, Math.max(2, Math.ceil(nI / (2 * N))));
    const PASO = 4.3, zF = 3.1, zI = zF + fF * PASO + 1.3;
    D = Math.max(23.4, zI + fI * PASO + 0.3); W = 34.8;
    const lote = new Lote(), caja = (mat, x, y, z, sx, sy, sz, ry = 0) => lote.pon(mat.uuid + 'c', G.caja, mat, M(x, y, z, ry, sx, sy, sz));

    // casco: losa, suelo, paredes del fondo y de la izquierda (las otras dos no están: se mira desde ahí)
    caja(MAT.losa, W / 2, -0.25, D / 2, W + 0.7, 0.5, D + 0.7);
    const suelo = new THREE.Mesh(G.plano, MAT.suelo); suelo.rotation.x = -Math.PI / 2; suelo.position.set(W / 2, 0.003, D / 2); suelo.scale.set(W, D, 1); suelo.receiveShadow = true; mobiliario.add(suelo);
    caja(MAT.pared, W / 2, 1.7, -0.11, W + 0.44, 3.4, 0.22); caja(MAT.pared, -0.11, 1.7, D / 2, 0.22, 3.4, D);
    caja(MAT.laton, W / 2, 3.42, -0.11, W + 0.46, 0.05, 0.25); caja(MAT.laton, -0.11, 3.42, D / 2, 0.25, 0.05, D);
    // ventanal del fondo sobre la sala de trading
    const cielo = new THREE.Mesh(G.plano, new THREE.MeshBasicMaterial({ map: texCielo })); cielo.position.set(8.9, 2.0, 0.012); cielo.scale.set(14.6, 2.1, 1); mobiliario.add(cielo);
    for (let i = 0; i <= 8; i++) caja(MAT.metal, 1.6 + i * 1.825, 2.0, 0.04, 0.06, 2.16, 0.07);
    caja(MAT.metal, 8.9, 3.07, 0.04, 14.7, 0.07, 0.07); caja(MAT.metal, 8.9, 0.94, 0.05, 14.7, 0.08, 0.12);
    // pantalla grande de la pared izquierda
    const zm = Math.min(D - 6.2, zF + 4.6);
    caja(MAT.monitor, 0.03, 2.05, zm, 0.08, 2.45, 9.5);
    const muro = new THREE.Mesh(G.plano, new THREE.MeshBasicMaterial({ map: texMuro, toneMapped: false })); muro.position.set(0.08, 2.05, zm); muro.rotation.y = Math.PI / 2; muro.scale.set(9.3, 2.3, 1); mobiliario.add(muro);
    const marca = cartel('Fondo IA', 3.2, 0.62, '#b6923f'); marca.position.set(0.02, 2.5, Math.min(D - 2.4, zm + 7.2)); marca.rotation.y = Math.PI / 2; marca.userData.propio = true; mobiliario.add(marca);

    // sala de trading e incubadora: bancadas de mesas enfrentadas
    asientos = { aprobada: [], incubadora: [] };
    const bancadas = (estado, z0, filas, alfombra, nombre) => {
      const a = new THREE.Mesh(G.plano, alfombra); a.rotation.x = -Math.PI / 2; a.position.set(8.5, 0.008, z0 + filas * PASO / 2 - 0.55); a.scale.set(14.6, filas * PASO - 0.5, 1); a.receiveShadow = true; mobiliario.add(a);
      const r = cartel(nombre, 3.4, 0.5, '#3d3a30'); r.rotation.x = -Math.PI / 2; r.position.set(3.2, 0.014, z0 + filas * PASO - 1.15); r.material.opacity = 0.6; r.userData.propio = true; mobiliario.add(r);
      zonas[estado] = [1.2, z0 - 0.9, 15.8, z0 + filas * PASO - 0.3];
      for (let f = 0; f < filas; f++) {
        const zb = z0 + f * PASO;
        for (const [dz, giro] of [[0, 0], [0.6 + 2 * DD, Math.PI]]) for (let c = 0; c < N; c++) {
          const x = X0 + (c + 0.5) * DW, z = zb + dz;
          asientos[estado].push({ x, z, giro, pantalla: puesto(lote, mobiliario, x, z, giro) });
        }
        caja(MAT.tela, X0 + N * DW / 2, 0.98, zb + 0.3 + DD, N * DW, 0.4, 0.03);                                   // biombo entre las dos hileras
      }
    };
    bancadas('aprobada', zF, fF, MAT.alfMesa, 'Mesa de trading');
    bancadas('incubadora', zI, fI, MAT.alfInc, 'Incubadora');

    // despachos
    for (const s of SALAS) {
      if (s.zona && !activos.has(s.zona)) continue;
      const x = COL[s.col], w = ANCHO_COL[s.col], z = s.z, d = s.d, g = new THREE.Group();
      g.position.set(x, 0, z); mobiliario.add(g);
      const tono = css('--z-' + s.id) || '#dddddd', alf = new THREE.Mesh(G.plano, std(tono, { roughness: 1 }));
      alf.rotation.x = -Math.PI / 2; alf.position.set(w / 2, 0.009, d / 2); alf.scale.set(w - 0.1, d - 0.1, 1); alf.receiveShadow = true; alf.userData.propio = true; g.add(alf);
      // mamparas de vidrio con marco de latón: fondo y lado izquierdo; el frente queda abierto hacia quien mira
      const vid = (px, pz, sx, sz) => { const m = new THREE.Mesh(G.caja, MAT.vidrio); m.position.set(px, 1.15, pz); m.scale.set(sx, 2.3, sz); g.add(m); };
      vid(w / 2, 0.03, w, 0.03); vid(0.03, d / 2, 0.03, d);
      caja(MAT.laton, x + w / 2, 2.31, z + 0.03, w, 0.04, 0.06); caja(MAT.laton, x + 0.03, 2.31, z + d / 2, 0.06, 0.04, d);
      for (const [px, pz] of [[0.03, 0.03], [w - 0.03, 0.03], [0.03, d - 0.03]]) caja(MAT.laton, x + px, 1.15, z + pz, 0.05, 2.3, 0.05);
      const c = cartel(s.nombre, Math.min(w - 0.8, 2.6), 0.36, '#f4f0e4', '#1b2a33'); c.position.set(w / 2, 2.03, 0.09); c.userData.propio = true; g.add(c);
      const sitio = (clave, px, pz, giro, de_pie) => { puestos[clave] = { x: x + px, z: z + pz, giro, de_pie }; if (!de_pie) return puesto(lote, mobiliario, x + px, z + pz, giro); };
      if (s.clase === 'riesgos') {
        for (let i = 0; i < 3; i++) { const p = new THREE.Mesh(G.plano, new THREE.MeshBasicMaterial({ map: texRiesgos, toneMapped: false })); p.position.set(0.95 + i * 1.8, 1.2, 0.08); p.scale.set(1.65, 0.92, 1); g.add(p); caja(MAT.monitor, x + 0.95 + i * 1.8, 1.2, z + 0.06, 1.72, 0.99, 0.03); }
        sitio('rie', w / 2, 2.2, 0);
      } else if (s.clase === 'comite') {
        caja(MAT.madera, x + w / 2 + 0.3, 0.73, z + d / 2 + 0.3, 3.3, 0.05, 1.15); caja(MAT.metal, x + w / 2 - 0.9, 0.355, z + d / 2 + 0.3, 0.06, 0.71, 0.8); caja(MAT.metal, x + w / 2 + 1.5, 0.355, z + d / 2 + 0.3, 0.06, 0.71, 0.8);
        const silla = (px, pz, giro) => { const b = M(x + px, 0, z + pz, giro); lote.pon('asiento', G.asiento, MAT.silla, b.clone().multiply(M(0, 0.42, -0.02))); lote.pon('respaldo', G.respaldo, MAT.silla, b.clone().multiply(M(0, 0.74, -0.25, 0, 1, 1, 1, -0.1)));
          lote.pon('pie', G.cil, MAT.metal, b.clone().multiply(M(0, 0.22, -0.02, 0, 0.03, 0.36, 0.03))); lote.pon('base', G.cil, MAT.metal, b.clone().multiply(M(0, 0.04, -0.02, 0, 0.27, 0.035, 0.27))); };
        for (let i = 0; i < 3; i++) { silla(w / 2 - 0.7 + i, d / 2 - 0.65, 0); silla(w / 2 - 0.7 + i, d / 2 + 1.25, Math.PI); }
        silla(w / 2 + 2.25, d / 2 + 0.3, -Math.PI / 2); silla(w / 2 - 1.65, d / 2 + 0.3, Math.PI / 2);
        puestos.com = { x: x + w / 2 - 1.65, z: z + d / 2 + 0.3, giro: Math.PI / 2 };
        caja(MAT.monitor, x + w / 2, 1.35, z + 0.07, 2.0, 1.1, 0.04);
      } else if (s.clase === 'laboratorio') {
        for (let i = 0; i < 4; i++) {
          caja(MAT.rack, x + 0.8 + i * 1.25, 1.0, z + 0.65, 0.8, 2.0, 0.9);
          const t = lienzo(64, 128, (c2, w2, h2) => { c2.fillStyle = '#0c1114'; c2.fillRect(0, 0, w2, h2); const r = azar(i + 40); for (let a = 0; a < 11; a++) for (let b = 0; b < 4; b++) { c2.fillStyle = r() < 0.7 ? '#46d39c' : '#e9b24c'; c2.fillRect(8 + b * 13, 8 + a * 11, 8, 4); } });
          const m = new THREE.Mesh(G.plano, new THREE.MeshStandardMaterial({ color: '#0c1114', emissive: '#ffffff', emissiveMap: t, emissiveIntensity: 0.15, roughness: 0.4 }));
          m.position.set(0.8 + i * 1.25, 1.05, 1.11); m.scale.set(0.62, 1.7, 1); m.userData.propio = true; g.add(m); racks.push(m);
        }
        sitio('lab', 1.5, 2.9, 0); sitio('lab2', 3.6, 2.9, 0);
        puertaLab = [x - 0.6, z + d / 2];
      } else if (s.clase === 'debate') {
        caja(MAT.blanco, x + w / 2, 1.45, z + 0.08, 2.6, 1.25, 0.04); caja(MAT.metal, x + w / 2, 0.8, z + 0.08, 2.66, 0.04, 0.07);
        sitio('alc', w / 2 - 1.25, 2.1, 0.95, true); sitio('baj', w / 2 + 1.25, 2.1, -0.95, true); sitio('mod', w / 2, 1.0, 0, true);
      } else sitio(s.gente[0], w / 2, 1.25, 0);
    }
    // plantas en esquinas y a lo largo del pasillo
    planta(lote, 0.9, 1.0, 1.25); planta(lote, 0.9, D - 0.9, 1.25); planta(lote, W - 0.8, D - 0.9, 1.2); planta(lote, PASILLO + 0.9, zI - 1.0, 1.05); planta(lote, PASILLO - 0.6, D - 0.9, 1.05);
    lote.volcar(mobiliario);
    mobiliario.traverse(o => { if (o.isInstancedMesh && (o.material === MAT.vidrio || o.material === MAT.lampara)) o.castShadow = false; });

    sol.position.set(W * 0.5 + 14, 26, D * 0.5 + 9); sol.target.position.set(W * 0.45, 0, D * 0.45);
    const cam = sol.shadow.camera; cam.left = -W * 0.62; cam.right = W * 0.62; cam.top = D * 0.75; cam.bottom = -D * 0.75; cam.near = 4; cam.far = 70; cam.updateProjectionMatrix();
    sombras = 3;
  }

  // ---------------------------------------------------------------- tema (día / noche según el del sistema)
  function tema() {
    const noche = oscuroMQ.matches;
    hemi.intensity = noche ? 0.3 : 0.7; hemi.color.set(noche ? '#8fa6c8' : '#ffffff'); hemi.groundColor.set(noche ? '#1a2229' : '#8f9288');
    sol.intensity = noche ? 0.6 : 3.1; sol.color.set(noche ? '#ffd9a0' : '#fff3df');
    escena.environmentIntensity = noche ? 0.25 : 0.55; renderer.toneMappingExposure = noche ? 1.05 : 1.0;
    MAT.pared.color.set(noche ? '#22333e' : '#eef0ec'); MAT.suelo.color.set(noche ? '#2a3a44' : '#c9cfca'); MAT.losa.color.set(noche ? '#16242d' : '#c4cbc8');
    MAT.alfMesa.color.set(noche ? '#6d6240' : '#cdb679'); MAT.alfInc.color.set(noche ? '#33506f' : '#93b1d6'); MAT.lampara.emissiveIntensity = noche ? 2.6 : 1.1;
    for (const k in PANT) PANT[k].emissiveIntensity = (k === 'fuera' ? 0.5 : 1.25) * (noche ? 1.5 : 1);
    texCielo.repintar((c, w, h) => {
      const g = c.createLinearGradient(0, 0, 0, h);
      if (noche) { g.addColorStop(0, '#0b1626'); g.addColorStop(1, '#24364f'); } else { g.addColorStop(0, '#9cc4e6'); g.addColorStop(1, '#e6f0f3'); }
      c.fillStyle = g; c.fillRect(0, 0, w, h);
      const r = azar(91);
      for (let x = 0; x < w;) {                              // silueta de la ciudad
        const bw = 40 + r() * 90, bh = 50 + r() * 150;
        c.fillStyle = noche ? '#13202e' : `rgb(${150 + r() * 30},${165 + r() * 25},${180 + r() * 20})`; c.fillRect(x, h - bh, bw - 4, bh);
        for (let yy = h - bh + 8; yy < h - 6; yy += 13) for (let xx = x + 6; xx < x + bw - 12; xx += 11) if (r() < (noche ? 0.33 : 0.5)) { c.fillStyle = noche ? '#f1cf85' : 'rgba(255,255,255,.4)'; c.fillRect(xx, yy, 5, 7); }
        x += bw;
      }
    });
    sombras = 2;
  }

  // ---------------------------------------------------------------- lo que cambia con cada /api/estado
  function pintarMuros() {
    const f = e.fondo, r = e.riesgos, apoyo = e.apoyo || {}, an = e.analistas || {};
    texMuro.repintar((c, w, h) => {
      c.fillStyle = '#0e1a22'; c.fillRect(0, 0, w, h);
      c.textBaseline = 'alphabetic'; c.textAlign = 'left';
      c.fillStyle = '#93a7ad'; c.font = `500 34px ${FUENTE}`; c.fillText('Patrimonio', 56, 84);
      c.fillStyle = '#f4f1e6'; c.font = `700 118px ${FUENTE}`; c.fillText(op.num(f.equity) + ' $', 52, 212);
      const hoy = r.kill ? 'Parado' : 'Hoy ' + op.pct(f.hoy);
      c.fillStyle = r.kill || f.hoy < 0 ? '#f07a7a' : f.hoy > 0 ? '#58d67c' : '#c9a24b'; c.font = `600 60px ${FUENTE}`; c.fillText(hoy, 56, 306);
      c.fillStyle = '#93a7ad'; c.font = `500 30px ${FUENTE}`; c.fillText(`Desde el inicio ${op.pct(f.total)}, ${op.num(f.invertido * 100, 0)} % invertido`, 480, 300);
      const x0 = 900; c.fillStyle = '#243843'; c.fillRect(x0 - 40, 44, 2, h - 88);
      const lineas = [['Mercado', apoyo.macro ? `${apoyo.macro.tendencia}, ${apoyo.macro.clima}` : 'sin leer aún'],
        ['Miedo y codicia', an.sentimiento ? `${an.sentimiento.valor} de 100, ${an.sentimiento.etiqueta}` : 'sin leer aún'],
        ['Plantilla', `${e.estrategias.filter(x => x.estado === 'aprobada').length} con capital, ${e.estrategias.filter(x => x.estado !== 'aprobada').length} en incubadora`]];
      lineas.forEach(([k, v], i) => { c.fillStyle = '#93a7ad'; c.font = `500 28px ${FUENTE}`; c.fillText(k, x0, 82 + i * 100); c.fillStyle = '#f4f1e6'; c.font = `600 40px ${FUENTE}`; c.fillText(v, x0, 130 + i * 100); });
    });
    texRiesgos.repintar((c, w, h) => {
      c.fillStyle = '#0e1a22'; c.fillRect(0, 0, w, h);
      if (r.kill) { c.fillStyle = '#f07a7a'; c.font = `700 84px ${FUENTE}`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('PARADO', w / 2, h / 2); return; }
      c.textAlign = 'left'; c.textBaseline = 'alphabetic';
      r.limites.forEach((l, i) => {
        const y = 38 + i * 56, uso = Math.min(1, l.uso / l.max);
        c.fillStyle = '#93a7ad'; c.font = `500 26px ${FUENTE}`; c.fillText(l.nombre, 30, y + 8);
        c.fillStyle = '#243843'; c.fillRect(330, y - 12, 400, 22);
        c.fillStyle = uso >= 1 ? '#f07a7a' : uso >= 0.8 ? '#e9b24c' : '#c9a24b'; c.fillRect(330, y - 12, Math.max(4, 400 * uso), 22);
      });
    });
  }
  function estadoPantalla(d) {
    if ((e.riesgos.kill && d.estado === 'aprobada') || d.pausa_hasta) return 'pausa';
    return d.pos > 0 ? 'largo' : d.pos < 0 ? 'corto' : 'fuera';
  }
  function actualizar(estado) {
    e = estado;
    activos = new Set(e.departamentos || e.eventos.map(x => x.origen));
    const nF = e.estrategias.filter(x => x.estado === 'aprobada').length, nI = e.estrategias.length - nF;
    const nueva = [Math.ceil(nF / (2 * N)), Math.ceil(nI / (2 * N)), SALAS.filter(s => !s.zona || activos.has(s.zona)).map(s => s.id).join()].join('|');
    const reconstruida = nueva !== firma;
    if (reconstruida) { firma = nueva; construir(); if (primera) encuadrar(true); }
    pintarMuros();
    for (const m of racks) m.material.userData.minando = !!e.aprendizaje.en_curso;

    // traders: uno por estrategia. Cada uno conserva su mesa mientras siga en la misma zona; los nuevos ocupan la primera libre
    const vivos = new Set(), pendientes = [];
    for (const lista of Object.values(asientos)) for (const a of lista) { ponPantalla(a, 'fuera'); a.ocupa = null; }
    for (const d of [...e.estrategias].sort((a, b) => a.id - b.id)) {
      const p = personas.get('b' + d.id);
      if (p && !p.saliendo && asientos[d.estado].includes(p.asiento)) p.asiento.ocupa = p.clave; else pendientes.push(d.id);
    }
    for (const d of [...e.estrategias].sort((a, b) => a.id - b.id)) {
      const clave = 'b' + d.id;
      let p = personas.get(clave);
      const a = pendientes.includes(d.id) ? asientos[d.estado].find(x => !x.ocupa) : p.asiento;
      if (!a) { if (p) despedir(p); continue; }             // no cabe nadie más: sigue en las tablas
      const nuevo = !p;
      if (nuevo) {
        const r = azar(d.id * 31 + 5), ropa = d.estado === 'aprobada' ? CAMISAS : SUDADERAS;
        p = crearPersona(clave, d.id, ropa[Math.floor(r() * ropa.length)], d.apodo || 'Bot');
        p.raiz.position.set(puertaLab[0], 0, puertaLab[1]);
      }
      a.ocupa = clave; p.d = d; p.id = d.id; p.saliendo = false;
      const pant = estadoPantalla(d);
      p.activo = pant === 'largo' || pant === 'corto';
      ponPantalla(a, pant);
      if (p.asiento !== a) colocar(p, a, !primera && !reconstruida);
      vivos.add(clave);
    }
    // personal de los departamentos
    for (const [k, def] of Object.entries(op.personal)) {
      const clave = 'p-' + k, sitio = puestos[k];
      if (!sitio) { const p = personas.get(clave); if (p) quitar(p); continue; }
      let p = personas.get(clave);
      if (!p) { p = crearPersona(clave, k.charCodeAt(0) * 131 + k.charCodeAt(1) * 7 + k.length, css(def.c) || '#888888', def.nombre); p.personal = k; }
      p.activo = k.startsWith('lab') ? !!e.aprendizaje.en_curso : ['alc', 'baj'].includes(k) ? true : k !== 'com' && k !== 'mod';
      if (p.asiento !== sitio) colocar(p, sitio, false);
      vivos.add(clave);
    }
    for (const p of [...personas.values()]) if (!vivos.has(p.clave) && !p.saliendo) despedir(p);

    const lider = e.estrategias.filter(d => d.dias !== undefined && d.trades > 0 && d.retorno > 0).sort((a, b) => b.retorno - a.retorno)[0];
    estrella.userData.de = lider && personas.has('b' + lider.id) ? 'b' + lider.id : null;
    // eventos nuevos: salen como bocadillos sobre quien los ha protagonizado
    const ultimoId = e.eventos.length ? e.eventos[e.eventos.length - 1].id : 0;
    if (vistoEv === null) vistoEv = Math.max(0, ultimoId - 2);
    cola.push(...e.eventos.filter(x => x.id > vistoEv)); if (cola.length > 6) cola = cola.slice(-6);
    vistoEv = ultimoId; primera = false; sombras = Math.max(sombras, 2);
  }

  // ---------------------------------------------------------------- cámara
  function encuadrar(yaMismo) {                            // la distancia justa para que quepa el edificio entero
    const c = new THREE.Vector3(W * 0.5, 0.3, D * 0.55), dir = new THREE.Vector3(Math.sin(0.66) * Math.sin(0.9), Math.cos(0.9), Math.cos(0.66) * Math.sin(0.9));
    const actual = camara.position.distanceTo(control.target) || 40, esquinas = [];
    for (const x of [-0.4, W + 0.4]) for (const z of [-0.4, D + 0.4]) for (const y of [0, 3.5]) esquinas.push(new THREE.Vector3(x, y, z));
    let d = 20;
    for (; d < 160; d += 1.5) {
      camara.position.copy(c).addScaledVector(dir, d); camara.lookAt(c); camara.updateMatrixWorld(); camara.updateProjectionMatrix();
      if (esquinas.every(v => { const q = v.clone().project(camara); return Math.abs(q.x) < 0.97 && q.y < 0.9 && q.y > -0.97; })) break;
    }
    control.minDistance = 5; control.maxDistance = d * 1.2;
    d *= 0.78;                                             // un poco más cerca que "todo entero": las esquinas vacías no aportan nada
    control.target.copy(c); distObjetivo = d;
    camara.position.copy(c).addScaledVector(dir, yaMismo ? d : actual);      // al centrar a mano, el zoom vuelve suavemente
    control.update();
  }
  function acercar(f) { distObjetivo = Math.min(control.maxDistance, Math.max(6, distObjetivo * f)); }
  tela.addEventListener('wheel', ev => { if (!ev.ctrlKey) return; ev.preventDefault(); acercar(ev.deltaY > 0 ? 1.12 : 0.89); }, { passive: false });

  const cabezaMundo = p => p.cabeza.getWorldPosition(new THREE.Vector3());
  function enPantalla(p, extra = 0.3) {
    const v = cabezaMundo(p); v.y += extra; v.project(camara);
    return [(v.x + 1) / 2 * tela.clientWidth + tela.offsetLeft, (1 - v.y) / 2 * tela.clientHeight + tela.offsetTop, v.z];
  }
  function cerca(ev) {
    const r = tela.getBoundingClientRect(), x = ev.clientX - r.left + tela.offsetLeft, y = ev.clientY - r.top + tela.offsetTop;
    let mejor = null, min = 30;
    for (const p of personas.values()) { if (p.saliendo) continue; const [sx, sy, sz] = enPantalla(p, -0.15); if (sz > 1) continue; const k = Math.hypot(sx - x, sy - y); if (k < min) { min = k; mejor = p; } }
    return mejor;
  }
  let abajo = null;
  tela.addEventListener('pointerdown', ev => { abajo = [ev.clientX, ev.clientY]; });
  tela.addEventListener('pointerup', ev => {
    if (!abajo || Math.hypot(ev.clientX - abajo[0], ev.clientY - abajo[1]) > 6) return;
    const p = cerca(ev);
    seleccion = p ? p.clave : null;
    op.alSeleccionar(p ? (p.personal ? { tipo: 'personal', clave: p.personal } : { tipo: 'bot', id: p.id }) : null);
  });
  tela.addEventListener('pointermove', ev => { encima = cerca(ev); tela.style.cursor = encima ? 'pointer' : 'grab'; if (encima) rotulo.textContent = encima.nombre + (encima.personal ? '' : ', n.º ' + encima.id); });
  tela.addEventListener('pointerleave', () => { encima = null; });

  // ---------------------------------------------------------------- bucle
  function globosYRotulo(ahora) {
    while (cola.length && globos.length < 2) {
      const ev = cola[0], id = +(/#(\d+)/.exec(ev.mensaje) || [])[1];
      const quien = (ev.origen === 'Mesa' || ev.origen === 'Incubadora') ? personas.get('b' + id) : [...personas.values()].find(p => p.personal && op.personal[p.personal].origenes.includes(ev.origen));
      if (quien && globos.some(g => g.quien.raiz.position.distanceTo(quien.raiz.position) < 5)) break;
      cola.shift();
      if (!quien) continue;
      const el = document.createElement('div'); el.className = 'bocadillo';
      const txt = quien.personal ? ev.mensaje : ev.mensaje.replace(/^#\d+ \S+ \S+ \S+: /, '');
      const b = document.createElement('b'); b.textContent = quien.nombre; el.append(b, txt.length > 130 ? txt.slice(0, 127) + '…' : txt);
      marco.appendChild(el); globos.push({ quien, el, hasta: ahora + 9000 });
    }
    globos = globos.filter(g => {
      if (ahora > g.hasta || !personas.has(g.quien.clave)) { g.el.remove(); return false; }
      const [x, y, z] = enPantalla(g.quien); g.el.hidden = z > 1;
      g.el.style.left = Math.max(120, Math.min(marco.clientWidth - 120, x)) + 'px'; g.el.style.top = (y - 6) + 'px'; return true;
    });
    if (encima && personas.has(encima.clave) && !globos.some(g => g.quien === encima)) { const [x, y] = enPantalla(encima, 0.22); rotulo.style.left = x + 'px'; rotulo.style.top = (y - 4) + 'px'; rotulo.hidden = false; } else rotulo.hidden = true;
  }
  function cuadro(ahora) {
    requestAnimationFrame(cuadro);
    if (!visible || document.hidden || !e || ahora - ultimoCuadro < 30) return;
    const dt = Math.min(0.1, (ahora - ultimo) / 1000), t = ahora / 1000; ultimo = ultimoCuadro = ahora;
    let andan = false;
    for (const p of personas.values()) {
      if (p.ruta) {
        andan = true;
        const dest = p.ruta[0], v = dest.clone().sub(p.raiz.position), dist = v.length(), paso = 2.6 * dt;
        if (dist <= paso) { p.raiz.position.copy(dest); p.ruta.shift(); if (!p.ruta.length) { p.ruta = null; const f = p.alLlegar; p.alLlegar = null; if (f) f(); } }
        else { p.raiz.position.addScaledVector(v, paso / dist); p.raiz.rotation.y = Math.atan2(v.x, v.z); }
      }
      if (personas.has(p.clave)) pose(p, t);
    }
    for (let i = 0; i < racks.length; i++) racks[i].material.emissiveIntensity = racks[i].material.userData.minando ? 0.9 + (quieto ? 0 : Math.sin(t * 5 + i * 1.7) * 0.5) : 0.15;
    const s = seleccion && personas.get(seleccion);
    anillo.visible = !!s; if (s) { anillo.position.set(s.raiz.position.x, 0.02, s.raiz.position.z); control.target.lerp(new THREE.Vector3(s.raiz.position.x, 0.6, s.raiz.position.z), 0.06); }
    const l = estrella.userData.de && personas.get(estrella.userData.de);
    estrella.visible = !!l; if (l) { const v = cabezaMundo(l); estrella.position.set(v.x, v.y + 0.34 + (quieto ? 0 : Math.sin(t * 2) * 0.03), v.z); estrella.rotation.y = quieto ? 0.6 : t * 1.2; }
    // zoom suave hacia la distancia pedida, sin tocar el ángulo
    const off = camara.position.clone().sub(control.target), dist = off.length();
    if (dist > 0.01 && Math.abs(dist - distObjetivo) > 0.02) camara.position.copy(control.target).addScaledVector(off, (dist + (distObjetivo - dist) * 0.14) / dist);
    control.target.x = Math.max(0, Math.min(W, control.target.x)); control.target.z = Math.max(0, Math.min(D, control.target.z)); control.target.y = Math.max(0, Math.min(3, control.target.y));
    control.update();
    if (sombras > 0 || andan) { renderer.shadowMap.needsUpdate = true; sombras--; }
    renderer.render(escena, camara);
    globosYRotulo(ahora);
  }
  function ajustar() {
    const w = marco.clientWidth; if (!w) return;
    const h = Math.round(Math.max(320, Math.min(700, w * 0.6)));
    renderer.setSize(w, h); camara.aspect = w / h; camara.updateProjectionMatrix(); sombras = 2;
  }
  new ResizeObserver(ajustar).observe(marco);
  new IntersectionObserver(xs => { visible = xs[0].isIntersecting; }).observe(marco);
  oscuroMQ.addEventListener('change', () => { tema(); if (e) { firma = ''; actualizar(e); } });
  setInterval(() => { sombras = Math.max(sombras, 1); }, 1500);          // las sombras se rehacen de vez en cuando, no en cada cuadro
  tema(); ajustar(); encuadrar(true);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (e) { firma = ''; actualizar(e); } });
  requestAnimationFrame(cuadro);

  return {
    actualizar, acercar, centrar: () => { seleccion = null; op.alSeleccionar(null); encuadrar(false); },
    limpiar: () => { globos.forEach(g => g.el.remove()); globos = []; rotulo.hidden = true; },
    info: () => ({ llamadas: renderer.info.render.calls, triangulos: renderer.info.render.triangles, personas: personas.size, andando: [...personas.values()].filter(p => p.ruta).length, camara: camara.position.toArray().map(v => +v.toFixed(1)), mira: control.target.toArray().map(v => +v.toFixed(1)), dist: +distObjetivo.toFixed(1) }),
    posiciones: () => [...personas.values()].map(p => { const r = tela.getBoundingClientRect(), [x, y] = enPantalla(p, -0.15); return { nombre: p.nombre, id: p.personal || p.id, x: r.left + x - tela.offsetLeft, y: r.top + y - tela.offsetTop }; }),
  };
}
