"""Agente que analiza CvLAC y GrupLAC (Minciencias, Colombia) con Claude, cvlac-json, gruplac-json y la DuckDB local.

  python agente_lac.py "¿Cuántos artículos de 2024 tiene GFIF (COL0008423) y cuántos están en el CvLAC de sus autores?"
  python agente_lac.py -i           # conversación: preguntas de seguimiento con el mismo contexto
  python agente_lac.py -v "..."     # muestra cada herramienta que el agente usa
  python agente_lac.py leer_gruplac COL0008423     # una herramienta sola, sin la API (la usa el subagente de
  python agente_lac.py consultar_sql "SELECT ..."  # Claude Code ~/.claude/agents/agente-lac.md); --actualizar descarga

Herramientas del agente:
  leer_cvlac(cod_rh)      el JSON guardado del CvLAC (o lo construye con cvlac-json, descargando la página)
  leer_gruplac(grupo)     el JSON guardado del GrupLAC (o lo construye con gruplac-json desde el HTML guardado)
  consultar_sql(sql)      SQL de solo lectura en cvlac_gruplac.duckdb (todos los CvLAC de UdeA y todos los GrupLAC)

Las credenciales de Anthropic se leen del entorno (ANTHROPIC_API_KEY). Lo que devuelven las herramientas (nombres,
títulos, periodos de vinculación) se envía a la API de Anthropic; nunca se envían cédulas.
"""

import argparse
import gzip
import json
import os
import sys
import time

import anthropic
import duckdb
from anthropic import beta_tool

BASE = os.path.expanduser(os.environ.get("MINCIENCIAS", "~/prog/claude/minciencias"))
DB = os.path.join(BASE, "cvlac_gruplac_db", "cvlac_gruplac.duckdb")
CVLAC_JSON = os.path.join(BASE, "cvlac-json", "data", "cvlac_udea")
GRUPLAC_JSON = os.path.join(BASE, "gruplac", "json")
GRUPLAC_HTML = os.path.join(BASE, "gruplac", "html")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agente_json")

MODEL = "claude-opus-5-5"
MAX_TURNS = 30  # llamadas al modelo por pregunta
MAX_ROWS = 200
PAUSE = 2.0  # segundos entre descargas de Minciencias
_last_download = [0.0]


def _pause():
    wait = PAUSE - (time.time() - _last_download[0])
    if wait > 0:
        time.sleep(wait)
    _last_download[0] = time.time()


def _load(path):
    with (gzip.open if path.endswith(".gz") else open)(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _save(name, d):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    return path


def _items(products, n=40):
    return [{"title": p.get("title") or p.get("name"), "year": p.get("year_published") or p.get("year")} for p in products[:n]]


@beta_tool
def leer_cvlac(cod_rh: str, actualizar: bool = False) -> str:
    """Resumen del CvLAC de un investigador: nombre, categoría, conteos por sección, experiencia y primeros productos.
    Usa el JSON guardado; con actualizar=true descarga la página de Minciencias y lo construye de nuevo (lento).
    Para listas completas o cruces con grupos usa consultar_sql.

    Args:
        cod_rh: COD_RH del investigador (identificador del CvLAC), p. ej. 0000177733.
        actualizar: true para descargar la página otra vez en lugar de usar el JSON guardado.
    """
    cod = cod_rh.strip().zfill(10)
    saved = next((p for p in (os.path.join(OUT, f"cvlac_{cod}.json"), os.path.join(CVLAC_JSON, f"cvlac_{cod}.json")) if os.path.exists(p)), None)
    if saved and not actualizar:
        d, origen = _load(saved), "JSON guardado"
    else:
        from cvlac_json import extract

        _pause()
        d = extract(cod)
        saved, origen = _save(f"cvlac_{cod}.json", d), "página descargada ahora"
    p = d.get("profile") or {}
    return json.dumps(
        {
            "origen": origen,
            "consultado": d.get("retrieved"),
            "cod_rh": cod,
            "nombre": p.get("full_name") or p.get("Nombre"),
            "categoria": p.get("Categoría"),
            "conteos": d.get("counts"),
            "experiencia": [{"institucion": e.get("institution") or e.get("name"), "periodo": e.get("period")} for e in (d.get("experience") or [])[:15]],
            "primeros_trabajos": _items(d.get("works") or []),
            "primeros_proyectos": _items(d.get("projects") or [], 15),
        },
        ensure_ascii=False,
        default=str,
    )


@beta_tool
def leer_gruplac(grupo: str, actualizar: bool = False) -> str:
    """Resumen de un grupo de investigación (GrupLAC): nombre, clasificación, líder, instituciones, conteos por sección,
    integrantes con su periodo de vinculación y primeros productos. Usa el JSON guardado; con actualizar=true descarga
    la página de Minciencias y lo construye de nuevo. Para listas completas usa consultar_sql.

    Args:
        grupo: código COL del grupo (p. ej. COL0008423) o número GrupLAC de 14 dígitos.
        actualizar: true para descargar la página otra vez en lugar de usar lo guardado.
    """
    from gruplac_json.parser import decode, extract, resolve

    nro, col = resolve(grupo.strip())
    key = col or nro
    candidates = [os.path.join(OUT, f"gruplac_{key}.json")] + [os.path.join(GRUPLAC_JSON, f"gruplac_{key}.json{s}") for s in ("", ".gz")]
    saved = next((p for p in candidates if os.path.exists(p)), None)
    if saved and not actualizar:
        d, origen = _load(saved), "JSON guardado"
    else:
        html_path = os.path.join(GRUPLAC_HTML, f"{nro}.html.gz")
        if os.path.exists(html_path) and not actualizar:
            with gzip.open(html_path) as fh:
                html, origen = decode(fh.read()), "HTML guardado"
        else:
            _pause()
            html, origen = None, "página descargada ahora"
        d = extract(key, html=html, log=lambda *a: None)
        _save(f"gruplac_{key}.json", d)
    p = d.get("profile") or {}
    return json.dumps(
        {
            "origen": origen,
            "consultado": d.get("retrieved"),
            "col": d.get("col"),
            "nro": d.get("nro"),
            "nombre": d.get("name"),
            "clasificacion": (p.get("classification") or {}).get("category"),
            "lider": p.get("leader"),
            "ciudad": p.get("city"),
            "area": p.get("knowledge_area"),
            "instituciones": [{"nombre": i.get("name"), "aval": i.get("status"), "ror": (i.get("ror") or {}).get("id")} for i in d.get("institutions") or []],
            "conteos": d.get("counts"),
            "integrantes": [{"nombre": m.get("full_name"), "cod_rh": m.get("cod_rh"), "periodo": m.get("period")} for m in d.get("members") or []][:150],
            "primeros_trabajos": _items(d.get("works") or []),
        },
        ensure_ascii=False,
        default=str,
    )


@beta_tool
def consultar_sql(sql: str) -> str:
    """Consulta SQL de solo lectura (DuckDB) sobre todos los CvLAC de UdeA y todos los GrupLAC. Devuelve hasta 200
    filas; los textos largos se recortan. Tablas y columnas en las instrucciones del sistema.

    Args:
        sql: la consulta, p. ej. SELECT kind, count(*) FROM products WHERE source = 'gruplac' GROUP BY 1.
    """
    try:
        con = duckdb.connect(DB, read_only=True)
    except duckdb.Error as e:
        return f"No se pudo abrir la base (¿se está actualizando?): {e}"
    try:
        cur = con.execute(sql)
        if cur.description is None:
            return "La consulta no devolvió filas."
        cols = [c[0] for c in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
        cut = len(rows) > MAX_ROWS
        rows = [[v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v for v in r] for r in rows[:MAX_ROWS]]
        return json.dumps({"columnas": cols, "filas": rows, "recortado_a_200_filas": cut}, ensure_ascii=False, default=str)
    except duckdb.Error as e:
        return f"Error SQL: {e}"
    finally:
        con.close()


TOOLS = [leer_cvlac, leer_gruplac, consultar_sql]

SYSTEM = """Eres un analista de la producción científica colombiana registrada en Minciencias: CvLAC (el currículo de
cada investigador, identificado por su COD_RH de 10 dígitos) y GrupLAC (la página de cada grupo, identificado por su
código COL, p. ej. COL0008423). Responde en el idioma de la pregunta, con cifras concretas, y di de dónde salen.

Herramientas: leer_cvlac y leer_gruplac dan un resumen de un CV o un grupo; consultar_sql consulta la base que reúne
4,596 CvLAC de investigadores de la Universidad de Antioquia y los 7,170 GrupLAC del país. Para cualquier pregunta que
pida listas, conteos, comparaciones o cruces, usa SQL. Descarga páginas (actualizar=true) solo si el usuario pide datos
actuales: cada descarga va a los servidores de Minciencias.

Tablas (DuckDB):
- persons(cod_rh, full_name, category, sex, nationality, url, retrieved, counts JSON, meta JSON)
- groups(col, nro, name, url, retrieved, category, leader, department, city, formed_year, knowledge_area VARCHAR[],
  certified, counts JSON, meta JSON)
- group_members(col, cod_rh, full_name, linkage, hours, period, start_year, start_month, end_year, end_month, open_end)
- group_institutions(col, name, status, ror_id, ror_name)
- products(source 'cvlac'|'gruplac', owner, product_id, kind 'work'|'project'|'event'|'patent'|'other', section, type,
  title, year, doi, endorsed, scienti_id, authors_count, authors_inferred, record JSON)
- product_authors(source, owner, product_id, position, full_name, cod_rh, role, product_hash)
- product_affiliations(source, owner, product_id, position, cod_rh, aff_id, aff_name, aff_type, country_code,
  years INTEGER[], provenance, detail JSON)
- product_external_ids(source, owner, product_id, id_source, id, provenance)
- vista hash_matches(product_hash, cod_rh, cvlac_owner, cvlac_product_id, gruplac_col, gruplac_product_id): un producto
  del CvLAC de una persona y el mismo producto de esa persona en un GrupLAC.

Reglas:
- owner es el COD_RH (source 'cvlac') o el código COL (source 'gruplac'; 234 grupos sin COL usan su número GrupLAC).
  Une productos con autores y afiliaciones por (source, owner, product_id), y cuenta product_id distintos.
- "Artículos": kind = 'work' AND section ILIKE 'Art%culos%' (GrupLAC 'Artículos publicados', CvLAC 'Artículos').
- product_hash = SHA-1 de título normalizado, COD_RH, tipo y año: mismo hash = mismo producto de la misma persona.
  Los proyectos nunca coinciden (GrupLAC no lista sus autores).
- Las afiliaciones son inferidas (experiencia del CvLAC, periodo de vinculación al grupo), no declaradas en la página;
  provenance dice la regla. Dilo cuando sea relevante.
- Los CvLAC cubren solo investigadores de UdeA: que un producto no esté en CvLAC puede significar que la persona no está
  en esa colección; compruébalo en persons.
- Para campos no aplanados usa record, p. ej. record->>'$.source.name' (revista de un trabajo).
- No muestres listas de más de 30 filas en la respuesta: resume y ofrece el detalle."""


def ask(client, messages, verbose=False):
    """Run the tool loop for the last user message; append every turn to messages (append-only) and return the text."""
    for _ in range(MAX_TURNS):
        r = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=[t.to_dict() for t in TOOLS],
            messages=messages,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "refusal":
            return "(El modelo declinó responder esta pregunta.)"
        if r.stop_reason == "max_tokens":
            return "".join(b.text for b in r.content if b.type == "text") + "\n(Respuesta cortada por longitud.)"
        uses = [b for b in r.content if b.type == "tool_use"]
        if not uses:
            return "".join(b.text for b in r.content if b.type == "text")
        results = []
        for u in uses:
            tool = next((t for t in TOOLS if t.name == u.name), None)
            if verbose:
                print(f"  → {u.name}({json.dumps(u.input, ensure_ascii=False)[:200]})", file=sys.stderr, flush=True)
            try:
                out = tool.call(u.input) if tool else f"Herramienta desconocida: {u.name}"
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": str(out)})
            except Exception as e:  # the model sees the error and can try another way
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"{type(e).__name__}: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    return "(Se alcanzó el límite de pasos sin una respuesta final.)"


def run_tool(argv):
    """Run one tool without the API: NAME ARG [--actualizar]; print its JSON or text."""
    name, rest = argv[0], argv[1:]
    actualizar = "--actualizar" in rest
    arg = " ".join(a for a in rest if a != "--actualizar")
    key = {"leer_cvlac": "cod_rh", "leer_gruplac": "grupo", "consultar_sql": "sql"}[name]
    inp = {key: arg, **({"actualizar": True} if actualizar and name != "consultar_sql" else {})}
    print(next(t for t in TOOLS if t.name == name).call(inp))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {t.name for t in TOOLS}:
        return run_tool(argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta", nargs="?")
    ap.add_argument("-i", "--interactivo", action="store_true", help="conversación con preguntas de seguimiento")
    ap.add_argument("-v", "--verbose", action="store_true", help="muestra las herramientas que usa el agente")
    args = ap.parse_args(argv)
    if not args.pregunta and not args.interactivo:
        ap.error("escribe una pregunta o usa -i")
    client = anthropic.Anthropic()
    messages = []
    question = args.pregunta
    while True:
        if question is None:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not question or question.lower() in ("salir", "exit", "quit"):
                return 0
        messages.append({"role": "user", "content": question})
        print(ask(client, messages, args.verbose))
        if not args.interactivo:
            return 0
        question = None


if __name__ == "__main__":
    sys.exit(main())
