# agente-lac

Agente que responde preguntas sobre CvLAC y GrupLAC (Minciencias, Colombia). Usa Claude (`claude-opus-5-5`) con tres
herramientas:

| Herramienta | Qué hace |
| --- | --- |
| `leer_cvlac(cod_rh, actualizar=false)` | Resumen de un CvLAC desde el JSON guardado (`cvlac-json/data/cvlac_udea/`); con `actualizar` descarga la página y lo reconstruye con cvlac-json |
| `leer_gruplac(grupo, actualizar=false)` | Resumen de un GrupLAC desde el JSON guardado (`gruplac/json/`), o desde el HTML guardado con gruplac-json; con `actualizar` descarga la página |
| `consultar_sql(sql)` | SQL de solo lectura en `cvlac_gruplac_db/cvlac_gruplac.duckdb` (4,596 CvLAC de UdeA y 7,170 GrupLAC), hasta 200 filas |

Los JSON que construye van a `agente_json/`. Entre descargas de Minciencias espera 2 s.

## Instalación

```bash
cd ~/prog/claude/minciencias/agente-lac
python3 -m venv --without-pip .venv
pip3 --python .venv/bin/python install anthropic cvlac-json gruplac-json duckdb
```

Clave de la API: créala en https://platform.claude.com (API Keys) y ponla en tu entorno, sin escribirla en archivos del
proyecto ni en el chat. Por ejemplo, en `~/.bashrc`:

```bash
export ANTHROPIC_API_KEY=...
```

## Uso

```bash
.venv/bin/python agente_lac.py "¿Cuántos artículos de 2024 tiene GFIF (COL0008423) y cuántos están en el CvLAC de sus autores?"
.venv/bin/python agente_lac.py -i      # conversación con preguntas de seguimiento
.venv/bin/python agente_lac.py -v "…"  # muestra cada herramienta que usa
```

## Sin API: subagente de Claude Code

La API de Anthropic se paga aparte de la suscripción Pro. Con Pro, usa el subagente
[`agents/agente-lac.md`](agents/agente-lac.md): tiene las mismas instrucciones y llama a las mismas herramientas con
Bash, sin la API. Claude Code lo encuentra con un enlace en tu carpeta de agentes:

```bash
mkdir -p ~/.claude/agents && ln -s "$PWD/agents/agente-lac.md" ~/.claude/agents/agente-lac.md
```

Las herramientas, sin la API:

```bash
.venv/bin/python agente_lac.py leer_cvlac 0000177733
.venv/bin/python agente_lac.py leer_gruplac COL0008423 [--actualizar]
.venv/bin/python agente_lac.py consultar_sql "SELECT count(*) FROM groups"
```

En cualquier sesión nueva de Claude Code: "usa agente-lac: ¿cuántos artículos de 2024 tiene GFIF?". Desde una terminal
con Claude Code autenticado (`claude` y luego `/login`): `claude -p "pregunta" --agent agente-lac`. Si cambias el
`SYSTEM` del script, cambia también el archivo del subagente.

## Cómo funciona

- Las herramientas se definen con `@beta_tool` del SDK `anthropic`, que genera su esquema desde la firma y el docstring.
- `ask()` repite el ciclo: llamar al modelo, ejecutar las herramientas que pide, devolver los resultados, hasta que
  responde (máximo 30 llamadas por pregunta). El historial solo crece, nunca se edita: así las preguntas de
  seguimiento de `-i` conservan el contexto, y los bloques de razonamiento del modelo siguen siendo válidos.
- Esfuerzo `high` (el predeterminado de Opus 5.5 es `medium`). Con `fallbacks="default"`, si el modelo declina una
  solicitud, otro modelo la continúa.
- Para agregar una herramienta: una función con `@beta_tool` y docstring con `Args:`, añadida a `TOOLS`; describe las
  tablas o reglas nuevas en `SYSTEM`.

## Privacidad y costos

- Lo que devuelven las herramientas (nombres, títulos, periodos de vinculación) se envía a la API de Anthropic. Las
  herramientas no leen los archivos con cédulas (`cod_rh_*.json`, `personas.json`).
- Cada pregunta cuesta varias llamadas al modelo; una pregunta con SQL suele tomar de 3 a 8.
- Si la base se está actualizando (`build_db.py`), `consultar_sql` responde que no pudo abrirla; repite la pregunta
  al terminar.
