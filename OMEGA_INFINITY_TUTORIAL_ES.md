# OMEGA INFINITY: tutorial de time-multiplexing externo

Paquete preparado para Kaoru Aguilera Katayama. Fecha: 9 de octubre de 2026.

El programa reutiliza las 16 compuertas del RTL que compartiste. La PC conserva
la fórmula, los valores de las variables y los resultados intermedios. La placa
Tiny Tapeout carga ventanas de hasta 16 operaciones y devuelve sus salidas antes
de que se sobrescriban. Este paquete no requiere regenerar el layout del ASIC.

## 1. Qué hace cada parte

| Parte | Trabajo |
| --- | --- |
| `run_sat_hw.py` | Cliente que ejecutas en la PC. |
| `omega_core.py` | Parser DIMACS, asignaciones y planificación por bloques. |
| `omega_transport.py` | Comunicación USB/CDC con mensajes JSON y confirmaciones. |
| `rp2040/omega_board_server.py` | Maneja los pines, reset y ciclos de reloj en la placa. |
| `rp2040/main.py` | Arranque del servidor usando el SDK oficial de Tiny Tapeout. |
| `omega_model.py` | Modelo funcional para probar el programa sin placa. |
| `examples/demo_300k/` | CNF de 300,000 variables y 100,000 cláusulas, con asignación conocida. |
| `make_demo.py` | Generador reproducible de más ejemplos. |
| `tests/` | Pruebas de parser, lógica, protocolo y controlador. |
| `rtl_reference/` | Copia sin cambios del Verilog que se analizó. |
| `RTL_PROFILE.json` | Perfil y huella SHA-256 de ese Verilog. |

Los archivos Python de la PC deben permanecer juntos. A la placa se copian
solamente los dos archivos de la carpeta `rp2040`.

### Los dos modos principales

**`evaluate`:** tú proporcionas una asignación, y las operaciones OR/AND de la
fórmula se evalúan mediante las compuertas. Una asignación rechazada no es una
decisión UNSAT sobre toda la fórmula.

**`solve`:** un solver de la PC busca una asignación global. Si encuentra una,
el programa la verifica mediante el mismo recorrido por bloques. Una decisión
UNSAT de este modo procede del solver de la PC. El informe identifica ambas
funciones por separado.

## 2. Preparar la PC

Necesitas Python 3.10 o posterior. Este paquete se comprobó con Python 3.12.
Descomprime el ZIP y abre una terminal dentro de `omega_time_multiplexing`, donde
está `run_sat_hw.py`.

Comprueba Python:

```bash
python --version
```

En Windows, si usas el lanzador `py`, puedes sustituir `python` por `py -3` en
los comandos de Python. En Linux/macOS puede llamarse `python3`.

Para usar la placa, instala las herramientas:

```bash
python -m pip install -r requirements.txt
```

Para activar la búsqueda SAT nativa opcional:

```bash
python -m pip install -r requirements-solver.txt
```

El paquete opcional se llama **`python-sat`**; el módulo que importa el programa
se llama `pysat`. La prueba sin placa funciona con la biblioteca estándar.

## 3. Primera prueba, sin placa

Ejecuta:

```bash
python run_sat_hw.py self-test --backend sim
```

El resultado esperado incluye:

```json
{
  "status": "SELF_TEST_PASS",
  "backend": "sim-functional-rtl",
  "gate_truth_table_cases": 28,
  "cross_block_and_multi_output": true
}
```

Comprueba la fórmula pequeña incluida:

```bash
python run_sat_hw.py evaluate examples/small.cnf --backend sim --assignment examples/small_assignment.txt --cross-check
```

Debe devolver `ASSIGNMENT_SATISFIES`. También puedes probar una asignación que
no la satisface:

```bash
python run_sat_hw.py evaluate examples/small.cnf --backend sim --all 0 --cross-check
```

En este caso devolverá `ASSIGNMENT_REJECTED` y código de salida 1.

## 4. Probar las 300,000 variables ahora

Ya hay un ejemplo listo dentro del ZIP. Todas las variables declaradas aparecen
en su fórmula; cada grupo de tres forma una cláusula. Su asignación conocida se
guarda en `assignment.txt`.

```bash
python run_sat_hw.py evaluate examples/demo_300k/demo.cnf --backend sim --assignment examples/demo_300k/assignment.txt --cross-check --report resultado_sim_300k.json
```

En el informe deben aparecer:

| Campo | Valor esperado |
| --- | --- |
| `status` | `ASSIGNMENT_SATISFIES` |
| `variables` | 300000 |
| `clauses` | 100000 |
| `literals` | 300000 |
| `blocks` | 25000 |
| `gates_written` | 400000 |
| `backend` | `sim-functional-rtl` |

Estas cifras corresponden a una evaluación de la asignación suministrada.
Los tiempos de `sim` son tiempos del modelo de software; el tiempo de USB y del
chip se mide al ejecutar el modo `serial`.

Para generar otro ejemplo:

```bash
python make_demo.py --vars 300000 --kind 3sat --seed 42 --out mi_demo_300k
```

Para crear una cláusula larga que cruza miles de ventanas y que usa `x300000`:

```bash
python make_demo.py --vars 300000 --kind chain --out mi_demo_cadena
python run_sat_hw.py evaluate mi_demo_cadena/demo.cnf --backend sim --assignment mi_demo_cadena/assignment.txt --cross-check
```

Los ejemplos son pruebas funcionales con solución conocida. Su tamaño no indica
que sean benchmarks difíciles de búsqueda SAT.

## 5. Preparar la placa Tiny Tapeout

Para ejecutar el modo físico necesitas la placa de desarrollo y el carrier con
tu ASIC, conectados por el USB de administración de la placa. Se usa el SDK
oficial de Tiny Tapeout para el mapa de pines, selección del proyecto y reloj.

La carpeta se llama `rp2040`, pero el servidor usa la API del SDK. La familia
anterior de placas usa RP2040; las placas ETR actuales pueden usar RP2350.
**Instala el firmware del SDK correspondiente a tu placa y microcontrolador.**
El SDK v3 del repositorio oficial se dirige a ETR/RP2350; para una placa RP2040
utiliza su firmware compatible de la familia anterior. Consulta los enlaces
oficiales al final. Un MicroPython genérico no incluye por sí solo `ttboard`.

Identifica el puerto:

```bash
mpremote connect list
```

En los comandos siguientes se usa `COM3` como ejemplo de Windows. Sustitúyelo
por el puerto que aparezca en tu equipo. En Linux suele ser `/dev/ttyACM0`;
en macOS utiliza la ruta `/dev/cu...` que muestre la lista.

Cierra otras terminales seriales y Tiny Tapeout Commander mientras uses el
cliente, para que el puerto tenga un solo dueño.

Antes de cambiar el arranque, comprueba que existe el SDK:

```bash
mpremote connect COM3 exec "from ttboard.demoboard import DemoBoard; print('SDK Tiny Tapeout disponible')"
```

El SDK también necesita los datos de tu shuttle y del proyecto. El nombre
esperado en este paquete es:

```text
tt_um_omega_infinity_kaoru
```

Si todavía no tienes la placa/carrier de tu envío, puedes completar las pruebas
de las secciones 3 y 4 y dejar esta instalación para cuando lleguen.

## 6. Copiar el servidor a la placa

Estos comandos cambian el programa del microcontrolador de administración.
Guarda primero los archivos que ya tiene la placa:

```bash
mpremote connect COM3 fs cp :main.py backup_main.py
mpremote connect COM3 fs cp :config.ini backup_config.ini
```

Si `config.ini` no existe, conserva la copia de `main.py` y continúa. Si ya
personalizaste `omega_board_server.py`, respáldalo también antes de sustituirlo.

Copia el servidor y su arranque:

```bash
mpremote connect COM3 fs cp rp2040/omega_board_server.py :omega_board_server.py
mpremote connect COM3 fs cp rp2040/main.py :main.py
mpremote connect COM3 reset
```

Espera a que la placa vuelva a aparecer como puerto USB. Si cambió de nombre,
repítelo en `mpremote connect list`.

El servidor arranca desde `main.py`. A partir de aquí usa `run_sat_hw.py` para
operar el chip. Un comando de `mpremote` que ejecute código puede interrumpir
el servidor; después de usarlo, reinicia la placa con `mpremote ... reset`.

## 7. Comprobar comunicación y perfil del chip

Primero:

```bash
python run_sat_hw.py probe --port COM3
```

El informe debe indicar `PROFILE_MATCH`, el proyecto esperado y:

```json
"base_bits": [0, 1, 0, 0, 1, 0, 1, 0]
```

Después ejecuta la prueba de las compuertas:

```bash
python run_sat_hw.py self-test --port COM3 --report prueba_chip.json
```

El resultado esperado es `SELF_TEST_PASS` con backend `serial-physical-asic`.
Esta prueba ejercita los siete opcodes, los 16 gates, lecturas de varios nodos
y el traslado de resultados entre ventanas.

El servidor detiene el reloj PWM después de seleccionar el proyecto. Para
cada gate coloca la configuración y genera un ciclo de reloj. Para leer otro
nodo, captura `target_node` con `prog_we=0`. Evita pulsar el botón de reloj
manual durante una transacción.

## 8. Evaluar una CNF mediante el ASIC

Comienza con el ejemplo pequeño:

```bash
python run_sat_hw.py evaluate examples/small.cnf --port COM3 --assignment examples/small_assignment.txt --cross-check --report resultado_chip_pequeno.json
```

Después ejecuta las 300,000 variables:

```bash
python run_sat_hw.py evaluate examples/demo_300k/demo.cnf --port COM3 --assignment examples/demo_300k/assignment.txt --cross-check --report resultado_chip_300k.json
```

El backend debe ser `serial-physical-asic`. La consola muestra progreso cada
1,000 bloques. `--cross-check` compara cada bloque con una referencia de CPU y
detiene el programa si sus resultados difieren. Puedes omitirlo en ejecuciones
posteriores para medir el recorrido sin esa comparación adicional.

Para tu propio archivo:

```bash
python run_sat_hw.py evaluate input.cnf --port COM3 --assignment mi_asignacion.txt --report resultado.json
```

El archivo de asignación admite literales con signo. Ejemplo para tres variables:

```text
s SATISFIABLE
v 1 -2 3 0
```

Esto significa `x1=1`, `x2=0`, `x3=1`. Debes dar un valor a cada variable usada
en la CNF. Si una variable declarada no aparece, se completa con 0.

`--all 0` y `--all 1` asignan un valor uniforme explícito:

```bash
python run_sat_hw.py evaluate input.cnf --port COM3 --all 1
```

## 9. Buscar una solución SAT y verificarla

Instala el solver opcional si todavía no lo hiciste:

```bash
python -m pip install -r requirements-solver.txt
```

Ejecuta:

```bash
python run_sat_hw.py solve input.cnf --port COM3 --solver pysat --model-out solucion.txt --report solucion.json
```

La búsqueda usa MiniSat22 a través de PySAT en la PC. Una candidata SAT se
envía al ASIC por bloques y debe superar la verificación antes de que el
programa escriba el modelo y anuncie SAT. Si la candidata falla la verificación,
el programa informa un error.

Puedes limitar los conflictos de la búsqueda:

```bash
python run_sat_hw.py solve input.cnf --port COM3 --solver pysat --conflicts 100000 --model-out solucion.txt --report solucion.json
```

Un presupuesto agotado produce `UNKNOWN`. El número de variables no determina
por sí solo la duración de la búsqueda.

Prueba didáctica sin PySAT ni placa, hasta 20 variables utilizadas:

```bash
python run_sat_hw.py solve examples/small.cnf --backend sim --solver brute --model-out solucion_pequena.txt
python run_sat_hw.py solve examples/unsat.cnf --backend sim --solver brute
```

## 10. Entender los mensajes

| Mensaje | Significado |
| --- | --- |
| `PROFILE_MATCH` | Comunicación y ocho nodos base coinciden con el perfil esperado. |
| `SELF_TEST_PASS` | Pasaron las pruebas digitales del backend elegido. |
| `ASSIGNMENT_SATISFIES` | La asignación suministrada hace verdadera la CNF. |
| `ASSIGNMENT_REJECTED` | Esa asignación hace falsa la CNF. |
| `SAT` en `solve` | El solver encontró una candidata y la evaluación la verificó. |
| `UNSAT` en `solve` | El solver de la PC concluyó que no hay asignación satisfactoria. |
| `UNKNOWN` | La búsqueda no obtuvo una decisión dentro del presupuesto. |
| `ERROR` | Comunicación, formato o verificación falló; no equivale a UNSAT. |

Códigos de salida: 0=éxito o decisión SAT/UNSAT; 1=asignación rechazada;
2=error; 3=UNKNOWN; 130=interrupción del usuario.

En `solve`, `verification_performed` indica si se evaluó una candidata.
`hardware_verified` solo vale `true` cuando esa verificación se ejecutó con el
backend serial. Una decisión UNSAT de la PC no activa ese campo.

## 11. Cómo se conserva una variable como x300000

En el RTL de referencia, los nodos base 0 y 1 son constantes 0 y 1. El cliente
consulta `assignment[300000]` en la PC y utiliza el nodo base correspondiente
como operando de la siguiente ventana. Los números globales de variable nunca
se recortan para meterlos directamente en `prog_a` o `prog_b`.

Cada ventana usa nodos 8..23 para sus 16 gates. Las cadenas colocan el resultado
anterior en A y el siguiente valor externo en B, respetando que `prog_b` tiene
solo cuatro bits. Antes de reiniciar los registros se leen las salidas que hacen
falta; los bits quedan en memoria de la PC y se codifican de nuevo como 0/1.

Se empaquetan varias cláusulas cortas en una ventana y se pueden leer varios
nodos de esa ventana. Una cláusula larga se divide entre ventanas y conserva
su OR parcial. Los resultados de las cláusulas se combinan mediante ventanas
AND del mismo chip.

El campo `grid_stable` se utiliza como señal de validez, tal como está conectado
en este RTL. El protocolo de este paquete prueba el camino digital de los gates;
una caracterización analógica de la malla es una medición distinta.

## 12. Resolver problemas de instalación

| Problema | Acción concreta |
| --- | --- |
| `No module named serial` | Ejecuta `python -m pip install -r requirements.txt` con el mismo Python del cliente. |
| `mpremote` no se reconoce | Usa el ejecutable instalado por pip o prueba `python -m mpremote`. |
| Puerto ocupado | Cierra Commander, terminales seriales y otros clientes del mismo puerto. |
| Timeout USB | Reinicia la placa, confirma el puerto y revisa que el servidor arranque. Puedes ver el arranque con `mpremote connect COM3 repl`; sal con Ctrl-X y reinicia antes de usar el cliente. |
| `No module named ttboard` | Instala el firmware oficial Tiny Tapeout adecuado para tu placa. |
| El SDK no detecta carrier/shuttle | Comprueba montaje del carrier y la versión/datos del SDK para ese envío. |
| El proyecto no aparece en el SDK | Revisa los datos oficiales de tu shuttle. Puedes consultar `tt.shuttle.find('omega')` desde la REPL del SDK. |
| Perfil de nodos base diferente | Compara el Verilog realmente enviado con `rtl_reference/project.v`; este paquete está diseñado para el perfil de taps constantes 0x52. |
| `No module named pysat` | Ejecuta `python -m pip install -r requirements-solver.txt`. |
| Error al instalar `python-sat` | Comprueba la guía oficial de instalación. Puedes seguir usando `evaluate`; la búsqueda nativa necesita que PySAT se instale correctamente. |
| Variables sin valor | Completa los literales de `mi_asignacion.txt` o usa `solve` para generar una candidata. |
| Discrepancia chip/referencia | Detén esa ejecución y revisa `probe`, reloj, selección del proyecto y dirección de pines antes de repetir `self-test`. |

Para restaurar el arranque anterior:

```bash
mpremote connect COM3 fs cp backup_main.py :main.py
mpremote connect COM3 reset
```

## 13. Pruebas y alcance de la entrega

Ejecuta las pruebas locales desde la raíz del paquete:

```bash
python -m unittest discover -s tests -v
```

Se comprobaron 23 pruebas de software: tablas de verdad, CNF aleatorias, ventanas
de 16 gates, identificadores altos, dos evaluaciones de una cláusula con 300,000
variables y un ejemplo de 300,000 variables/100,000 cláusulas. El cliente USB se
probó contra el servidor real de este paquete y un doble de SDK conectado al
modelo funcional. Esa prueba verifica el protocolo y los ciclos programados.

Hay además una prueba opcional con Icarus Verilog que ejecuta las transacciones
del planificador sobre `rtl_reference/project.v`. Si `iverilog` y `vvp` están
instalados, se activa automáticamente; si faltan, unittest la marca como omitida.

En esta entrega no se ejecutaron el ASIC físico, la simulación HDL opcional ni
el solver nativo PySAT. Los informes `validation/` indican el backend utilizado.
La búsqueda didáctica `brute` sí se comprobó. Para la primera ejecución física,
sigue el orden: `probe`, `self-test`, fórmula pequeña y luego fórmula grande.

## 14. Fuentes oficiales utilizadas para la integración

- [Tiny Tapeout: guía de placas TT04+ y SDK RP2040](https://tinytapeout.com/guides/get-started-demoboard/).
- [SDK Tiny Tapeout: API de puertos, selección, reset y reloj](https://github.com/TinyTapeout/tt-micropython-firmware).
- [Versiones oficiales del firmware; elegir el microcontrolador correcto](https://github.com/TinyTapeout/tt-micropython-firmware/releases).
- [MicroPython mpremote: transferencia de archivos y reinicio](https://docs.micropython.org/en/latest/reference/mpremote.html).
- [pySerial: API y timeouts](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
- [PySAT: instalación](https://pysathq.github.io/installation/).
- [PySAT: API de solvers y presupuesto de conflictos](https://pysathq.github.io/docs/html/api/solvers.html).

La huella del Verilog analizado está en `RTL_PROFILE.json`; los scripts de la PC
y de la placa se diseñaron contra esa interfaz concreta.
