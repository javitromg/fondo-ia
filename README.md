# Fondo IA

Un fondo que funciona solo: mina estrategias, las filtra, las prueba en papel, reparte capital
entre las que aguantan, vigila el riesgo cada minuto y vuelve a aprender cada semana con los
datos más recientes. Se sigue desde un panel web en vivo.

**Ahora mismo opera en papel.** Nada de este código envía órdenes reales ni necesita claves API.
Los datos de mercado son los públicos de Kraken (perpetuos).

## Arrancar

En Windows: doble clic en `INICIAR.bat`. Instala lo necesario la primera vez, arranca el fondo y abre el panel.
A mano, desde PowerShell:

```powershell
cd fondo-ia
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m pytest -q             # 37 comprobaciones del motor (un minuto)
python -m fondo demo --panel    # circuito completo con datos inventados y su panel en http://localhost:8765
```

Para dejarlo funcionando de verdad, un solo comando:

```powershell
python -m fondo auto
```

Y abre http://localhost:8765. Ese proceso hace todo sin que lo toques:

| Cada cuánto | Qué hace |
|---|---|
| Cada minuto | Marca posiciones a mercado, vigila los límites de riesgo y ejecuta las órdenes que tocan (en papel) |
| Cada hora | Actualiza el histórico de velas y funding |
| Cada día | Reúne al comité: promociona, retira capital, descarta y reparte |
| Cada 7 días | Vuelve a minar con los datos más recientes y manda lo que sobrevive a la incubadora |

La primera vez descarga 3 años de histórico y lanza la primera ronda de minería (alrededor de una
hora en segundo plano). Tiene que estar encendido para operar: en un PC que se apaga, el fondo se para.

Comandos sueltos, por si quieres hacer algo a mano:

```powershell
python -m fondo descargar    # baja o actualiza el histórico; si un símbolo no existe, lista los disponibles
python -m fondo minar        # una ronda de minería ahora (o doble clic en MINAR_AHORA.bat, que además actualiza datos)
python -m fondo incubar-ultima   # incubar en papel lo último minado aunque no hubiera evidencia; quedan marcadas "a prueba"
python -m fondo estado       # resumen en la consola
python -m fondo kill         # parar todo.  python -m fondo kill --reactivar  para volver a operar
python -m fondo panel        # solo el panel
```

Símbolos, timeframes, costes, límites y frecuencia de aprendizaje se cambian en `config.yaml`.

Para aplicar una actualización sin perder nada: crea un archivo vacío llamado `REINICIAR` en la carpeta. El programa se cierra
solo en cuanto no haya una búsqueda en marcha y `INICIAR.bat` lo vuelve a abrir con el código nuevo.

## Telegram (opcional)

Para que te avise al móvil y poder pararlo desde ahí:

1. En Telegram, abre un chat con **@BotFather**, envíale `/newbot` y sigue los pasos. Te dará un token.
2. Abre el archivo `telegram_token.txt` de la carpeta del fondo, pega dentro ese token, sin nada más, y guarda.
   El fondo lo detecta solo en un minuto; no hace falta reiniciar.
3. Antes de 15 minutos, envíale `/start` a tu bot. Queda vinculado a ese chat y ya no obedece a nadie más.

Te avisa de: paradas de emergencia y pausas, bots en modo seguro, decisiones del comité, lo que detecte Auditoría,
contrataciones y el cierre de cada día. Órdenes: `/estado`, `/liga`, `/parar`, `/reanudar` (estas dos piden `/confirmar`).

## El panel

- Sala: vista isométrica donde cada bot es una estrategia real. Su pantalla enseña la posición abierta (▲ largo, ▼ corto,
  apagada fuera), los bocadillos son órdenes y decisiones reales, el laboratorio solo se mueve mientras hay una minería
  en curso y los bots nuevos salen de ahí hacia la incubadora. Tocando un bot se ve su ficha. «Reunir al comité» lanza
  una reunión de verdad, con las mismas reglas que la diaria.
- Liga de bots: ranking por resultado. El primero lleva una estrella en la sala.
- Patrimonio, resultado del día y desde el inicio, caja e invertido.
- Margen de riesgo: cuánto se lleva gastado de cada límite antes de que Riesgos corte.
- Parada de emergencia: cierra todo y deja de operar hasta que lo reanudes.
- Aprendizaje: embudo de la última ronda, control de ruido, veredicto y fecha de la próxima.
- Estrategias con capital y en incubadora, con su resultado, caída, Sharpe y posición.
- Actividad: cada orden, cada decisión de Riesgos y cada acta del comité, filtrable.

El panel solo es accesible desde tu propio ordenador (127.0.0.1). Si se despliega en un servidor
hay que ponerle contraseña delante antes de exponerlo.

## La oficina en 3D

La sala del panel es una oficina en 3D (three.js, incluido en `fondo/static`, sin nada que instalar): arrastra para girar,
`+` y `−` para acercar (o Ctrl + rueda), botón derecho para desplazar y toca a cualquiera para ver su ficha.

- Cada persona de la sala de trading y de la incubadora es una estrategia. Conserva su mesa mientras siga en su zona.
- Su pantalla y el testigo de encima enseñan su posición: verde con ▲ largo, rojo con ▼ corto, apagada fuera de mercado, ámbar en modo seguro o con el fondo parado. Quien tiene posición teclea; quien no, está echado hacia atrás.
- Un bot nuevo sale andando del laboratorio hasta su mesa; uno despedido se levanta y se va por el pasillo.
- Cada despacho acristalado es un departamento y aparece cuando ha hecho su primer informe. Los bocadillos son eventos reales.
- La pantalla grande de la pared lleva patrimonio, resultado del día, mercado y sentimiento; las de Riesgos, el uso de los límites.
- Con el sistema en modo oscuro, la oficina se ve de noche.

Las personas son figuras modeladas, no fotorrealistas. Si el navegador no tiene WebGL se queda el plano de siempre, y el botón
«Plano» lo trae de vuelta cuando quieras.

## Cómo funciona

0. **Modo automático** (`auto.py`). Orquesta todo lo de abajo. Cada ronda de minería usa la ventana
   más reciente del histórico, así que el tramo de reserva (el examen final) son siempre los
   últimos meses de mercado.
1. **Minería** (`miner.py`). Prueba combinaciones aleatorias de 8 familias de estrategias
   (cruce de medias, Donchian, RSI, Bollinger, Ichimoku, momentum, MACD, Keltner y hora del día) mirando solo el
   primer 60 % del histórico. Por defecto mina **carteras**: un mismo juego de parámetros aplicado
   a todos los símbolos a la vez, con el capital a partes iguales. Es mucho más difícil de
   sobreajustar que afinar una estrategia para un solo símbolo (`mineria.modo: individual` o `ambos`
   para lo otro). En modo cartera prueba además estrategias **transversales**, que comparan las monedas
   entre sí: compran las más fuertes y venden las más débiles a la vez (o al revés), de modo que casi no
   dependen de que el mercado suba.
2. **Embudo de robustez** (`robustness.py`). Cada candidata tiene que pasar, en orden: validación
   en datos no vistos, consistencia por tramos, Monte Carlo sobre sus operaciones, vecindad de
   parámetros, el doble de costes y, al final, un 20 % de histórico reservado que se mira una sola vez.
3. **Control de ruido** (`pipeline.py`). Repite todo el proceso 9 veces sobre los mismos datos con
   cada vela invertida al azar alrededor de su subida media: mismo tamaño de movimientos, misma
   subida total, misma correlación entre monedas, pero sin patrón sobre cuándo se mueven. Lo que
   sobrevive ahí es suerte o simplemente haber estado comprado en un mercado que subía. Solo se
   considera que hay ventaja si casi ninguna ronda de ruido iguala los hallazgos reales (p ≤ 0,10).
   Si no, el informe lo dice y no se manda nada a la incubadora.
3b. **Selección de personal** (`rrhh.py`). Vigila la plantilla: si hay menos bots que el objetivo, pide al
   laboratorio una búsqueda extra (como mucho una al día) con combinaciones que no se habían probado. Además
   lleva la cuenta de qué tipos de estrategia sobreviven, llegan a tener capital o acaban despedidos, y
   reparte las pruebas de la siguiente ronda a favor de los que mejor historial tienen.
4. **Incubadora** (`paper.py`). Las supervivientes operan en papel con precios en vivo y capital
   ficticio, con las mismas reglas que el backtest. Hay un test que comprueba que ambos coinciden
   vela a vela.
5. **Comité** (`comite.py`), una vez al día. Promociona al fondo a quien cumple tiempo, operaciones
   y Sharpe mínimos; descarta a quien supera la caída máxima o agota el plazo; reparte capital
   por volatilidad inversa con tope por estrategia.
5b. **Auditoría** (`auditoria.py`), una vez al día. Vuelve a simular cada bot y compara lo que ha hecho en vivo
   con todos los tramos igual de largos de su histórico. Si rinde por debajo del 5 % peor, es que su histórico
   era un espejismo y el comité lo despide sin esperar a que pierda más. Si lo hecho en vivo no se parece a la
   simulación de esas mismas fechas, avisa.
5c. **Modo seguro por bot.** Si un bot encadena más operaciones perdedoras que nunca en su histórico (dos más que
   su peor racha, y como mínimo 6), se queda fuera del mercado 24 horas. No es un stop arbitrario: solo salta cuando
   pasa algo que su histórico no había visto.
6. **Riesgos** (`risk.py`). Código determinista por el que pasa toda orden del fondo: apalancamiento,
   exposición bruta, neta y por símbolo. Si el día pierde más del límite cierra todo hasta mañana;
   si la caída desde máximos supera el límite salta el kill switch y solo se reactiva a mano.

Cada orden, decisión de Riesgos y acta del comité queda en la tabla `eventos` de `fondo.db`.
Esa tabla es la que alimentará la sala visual y los agentes en la fase 4.

## Biblioteca de modelos publicados

La minería busca parámetros a ciegas y casi todo lo que encuentra es suerte. La biblioteca hace lo contrario: coge modelos
cuyas reglas ya están publicadas, sin afinar nada, y mira qué habrían hecho con las velas diarias de Kraken.

| Modelo | Qué hace | De dónde sale |
|---|---|---|
| `tendencia_conjunta` | Nueve modelos de canal de 5 a 360 días, solo largos. Cada uno entra cuando el cierre marca máximo de su ventana y sale con un stop que solo sube, en el punto medio del canal. La posición es la media de los nueve votos. | Zarattini, Pagani y Barbon (2025), «Catching Crypto Trends» |
| `impulso_conjunto` | Dentro mientras el precio esté por encima del de hace 1, 3 y 12 meses (un voto por ventana). | Impulso de serie temporal (Moskowitz, Ooi y Pedersen, 2012) aplicado a cripto |

Como no hay nada que ajustar, se evalúa todo el histórico de una vez y se compara con dos cosas: comprar y mantener todas las
monedas con el mismo control de tamaño, y el mismo modelo sobre 99 versiones "placebo" del histórico. Si mejora a comprar y
mantener, entra en la incubadora un bot por moneda; si además no se distingue del ruido, entran marcados "a prueba". A partir
de ahí los juzga el comité como a cualquier otro (los bots diarios operan poco: se les piden 3 operaciones y tienen 180 días).

Se revisa sola una vez por semana en modo automático. A mano: `python -m fondo biblioteca`. El resultado queda en
`informes/biblioteca.json` y en el bloque Aprendizaje del panel.

Para añadir un modelo: escribe la función en `fondo/strategies.py` con `@publicada(...)` y dale de alta en `MODELOS` de
`fondo/biblioteca.py` con su fuente.

## Departamentos de apoyo

Lo que un fondo de verdad tiene alrededor de la mesa. Todos son código con reglas fijas, trabajan solos y aparecen en la sala
en cuanto hacen su primer informe (`fondo/departamentos.py`).

| Departamento | Cuándo | Qué hace | ¿Toca algo? |
|---|---|---|---|
| Investigación | Cada semana | Lleva la biblioteca de modelos publicados (ver arriba). | Contrata bots a la incubadora. |
| Macro | Cada día | Estado del mercado: BTC frente a su media de 200 días, cuántas monedas acompañan, volatilidad y funding. | No. Informa, y avisa por Telegram si cambia el régimen. |
| Datos | Tras cada descarga | Que el histórico esté al día, sin huecos en 90 días y sin velas imposibles. | No. Avisa si algo está mal. |
| Ejecución | Mide cada ciclo, informa cada día | Horquilla real de cada moneda frente al deslizamiento supuesto. | Sí: a la moneda que sale más cara, la mesa le cobra lo medido. |
| Cartera | Cada día | Agrupa los bots por apuesta y mide a cuántas apuestas independientes equivalen. | Sí: tope de capital por apuesta (`riesgos.peso_max_apuesta`, 50 %). |
| Operaciones | Cada día y al arrancar | Cuadre: posición de cada cuenta contra su última orden, apalancamiento, precios recientes y límites del fondo. | No. Avisa por Telegram si algo no cuadra. |

## Analistas: sentimiento, noticias y debate

Informan a la casa. Ninguna orden ni reparto de capital depende de ellos (`fondo/analistas.py`).

| Departamento | Qué hace | ¿Necesita clave? |
|---|---|---|
| Sentimiento | Índice de miedo y codicia del mercado cripto (alternative.me). Avisa por Telegram cuando cambia de zona. | No |
| Noticias | Titulares de las últimas 24 horas de CoinDesk, Cointelegraph y Decrypt (RSS). Sin modelo los clasifica por palabras clave, que es tosco. Con modelo los resume y avisa por Telegram de los graves (un hackeo, una quiebra, una sanción). | No (mejor con ella) |
| Debate | Una vez al día un analista alcista y otro bajista defienden su postura con la misma hoja de datos y un moderador resume. | Sí |

Se actualizan cada 4 horas (`analistas.cada_horas`). En Telegram: `/analisis`.

**Para encender el modelo de lenguaje**: crea una clave de la API de Anthropic, pégala tú en un archivo `llm_clave.txt` dentro de la
carpeta del fondo (solo la clave, en la primera línea) y en menos de una hora se enciende solo. La API es de pago por uso; con el
modelo por defecto (`analistas.modelo`) y unas 9 consultas pequeñas al día, el gasto es de céntimos. Hay un tope de consultas
diarias (`analistas.llamadas_dia_max`). La clave solo se envía a la API y nunca aparece en el panel ni en los registros.

Los titulares son texto de terceros: al modelo se le pasan como datos y lo que contesta solo se muestra. No hay ninguna prueba
de que el debate mejore los resultados; está para leerlo, no para obedecerlo.

## Supuestos y límites del simulador

- La señal se decide al cierre de una vela y se ejecuta en la apertura de la siguiente.
- Costes por defecto: 0,05 % de comisión (taker de Kraken) y 0,04 % de slippage por lado, más funding
  (histórico real si se descargó; si no, 0,01 % cada 8 h).
- El tamaño se fija al abrir (volatilidad objetivo del 20 % anual, tope 2x). No hay stops
  intravela, ni liquidaciones, ni libro de órdenes: en real el deslizamiento puede ser mayor.
- Tres años de datos no bastan para demostrar estadísticamente una ventaja pequeña. La columna
  DSR del informe lo refleja: casi nada llega a 0,9. Por eso existen el control de ruido y la
  incubadora, y por eso lo normal es que la mayoría de rondas no dejen nada.
- Si no sobrevive nada, no relajes los filtros hasta que salga algo: eso es fabricar sobreajuste.

## Añadir una estrategia

En `fondo/strategies.py`, una función que devuelva +1 / -1 / 0 por vela usando solo datos hasta
esa vela, decorada con `@estrategia({...espacio de parámetros...})`. El test
`test_ninguna_estrategia_mira_al_futuro` la comprueba automáticamente.

## Fondo elitista: a quién se le da capital

El listón para pasar de la incubadora al fondo (`config.yaml`):

- **30 días** de rodaje en papel como mínimo, **Sharpe en vivo de 1,0 o más**, resultado positivo y las operaciones mínimas.
- Auditoría no puede estar diciendo que lo que hace en vivo no se parece a su simulación.
- Quien cae más de un **10 %** en pruebas, fuera; con capital, se le retira.
- Solo hay **10 plazas con capital** (`comite.max_con_capital`). Entran primero los de mejor Sharpe en vivo. Con las plazas llenas, un
  aspirante le quita el sitio al peor titular si lo mejora por al menos 0,5 de Sharpe y el titular ya lleva su rodaje.
- La minería solo contrata si lo encontrado gana a las **19 rondas de ruido** (p ≤ 0,05).

Con estas reglas puede pasar un mes entero sin nadie con capital. Un Sharpe medido en 30 días tiene mucho de suerte: el listón
filtra, no certifica.

## Ponerlo en un servidor (Railway u otro)

El proyecto trae `Dockerfile` y `arrancar.sh` (el equivalente a `INICIAR.bat` en Linux). En el servidor hace falta:

| Qué | Cómo |
|---|---|
| Disco persistente | Un volumen montado, por ejemplo en `/data`. En Railway el fondo lo detecta solo (`RAILWAY_VOLUME_MOUNT_PATH`); en otro sitio, variable `FONDO_DATOS=/data`. Ahí van la base, el histórico, los informes y las copias. Sin volumen, cada redespliegue lo borra todo. |
| Contraseña del panel | Variable `FONDO_CLAVE_PANEL`, de 10 caracteres o más. Sin ella el panel se queda **cerrado** hacia internet: solo responde `/salud` y no enseña ni acepta nada (el fondo sigue funcionando). |
| Telegram | Variable `TELEGRAM_TOKEN`. |
| Modelo de lenguaje (opcional) | Variable `ANTHROPIC_API_KEY`. |
| Puerto | El que dé el servidor en `PORT`; no hay que tocar nada. |
| Comprobación de salud | Ruta `/salud`: responde sin contraseña y solo dice si el proceso vive y cuántos segundos lleva sin ciclar. |
| Reinicio | Si el proceso muere, que el servidor lo reinicie ("on failure"). |
| Región | Europa: Kraken Futures no atiende desde Estados Unidos. |

Las claves las pones tú en el servidor; no van en el código ni en la imagen (`.dockerignore` las deja fuera).

Qué pasa con la seguridad del panel: sesión por galleta firmada que dura 30 días (`panel.sesion_dias`), cinco intentos fallidos
bloquean esa dirección un cuarto de hora, y cambiar la contraseña cierra todas las sesiones. En casa, sin contraseña, el panel
solo escucha en tu propio ordenador, como hasta ahora; si quieres contraseña también ahí, ponla en `panel_clave.txt`.

Lo que vigila al fondo cuando no lo miras:

- **Vigilante.** Si la mesa lleva más de 10 minutos sin completar un ciclo, aviso por Telegram, y otro cuando se recupera. Si el
  programa estuvo caído, lo cuenta al arrancar.
- **Copias.** Una copia diaria de la base en `copias/` (se guardan 7) y, los lunes, una comprimida a tu chat de Telegram: es la
  única que vive fuera del servidor.
- **Informe semanal.** Los lunes, por Telegram: resultado de la semana, mejores y peores bots, movimientos del comité, incidencias
  y consumo del modelo de lenguaje.

## Lo que falta

- **Ejecución real.** Un ejecutor de órdenes contra Kraken con claves API sin permiso de retirada,
  empezando con capital mínimo. No tiene sentido antes de que algo sobreviva semanas en la incubadora.
- **Calendario macro.** Un filtro que reduzca riesgo alrededor de eventos macro (tipos, IPC). Habría que
  probarlo antes contra el histórico, como todo lo demás.
