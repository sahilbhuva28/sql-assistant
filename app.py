"""
SQL Assistant — Preview. Understand. Never Break.
Hackathon-scoped build: SQLite only, safe rollback execution,
before/after diff, persistent cross-session memory (JSON-backed).

NOTE ON MEMORY:
This uses a simple JSON store (memory.json) to persist schema/query/error
history across sessions, standing in for a full Cognee graph-vector memory
layer. The shape of the data (entities: schema, query, error, timeline)
is deliberately kept close to what you'd hand to cognee.add() / cognee.search(),
so swapping in real Cognee later is a drop-in replacement of memory_store.py,
not a redesign.
"""

import sqlite3
import shutil
import json
import os
import time
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template

from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[warn] Gemini client failed to initialize, falling back to rule-based chat: {e}")
        gemini_client = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
MEMORY_FILE = os.path.join(BASE_DIR, "memory.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DANGEROUS_PATTERNS = ["drop table", "drop database", "truncate", "delete from"]


# ---------------------------------------------------------------------------
# Memory layer (JSON-backed placeholder for Cognee)
# ---------------------------------------------------------------------------

def _load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {"projects": {}}
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)


def _save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)


def remember(project_id, kind, payload):
    """kind: 'schema' | 'query' | 'error' | 'timeline'"""
    mem = _load_memory()
    mem["projects"].setdefault(project_id, {
        "schema": None, "queries": [], "errors": [], "timeline": []
    })
    entry = mem["projects"][project_id]

    if kind == "schema":
        entry["schema"] = payload
    elif kind == "query":
        entry["queries"].append(payload)
    elif kind == "error":
        entry["errors"].append(payload)

    entry["timeline"].append({
        "ts": datetime.utcnow().isoformat(),
        "kind": kind,
        "summary": payload.get("summary", "") if isinstance(payload, dict) else str(payload)
    })
    _save_memory(mem)


def recall(project_id):
    mem = _load_memory()
    return mem["projects"].get(project_id, {
        "schema": None, "queries": [], "errors": [], "timeline": []
    })


# ---------------------------------------------------------------------------
# Schema extraction
# ---------------------------------------------------------------------------

def extract_schema(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    schema = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [{"name": c[1], "type": c[2]} for c in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        schema[t] = {"columns": cols, "row_count": count}
    conn.close()
    return schema


def classify_risk(sql):
    lowered = sql.strip().lower()
    for pat in DANGEROUS_PATTERNS:
        if pat in lowered:
            if "delete from" in lowered and "where" not in lowered:
                return "danger", "DELETE without WHERE — affects all rows"
            if pat in ("drop table", "drop database", "truncate"):
                return "danger", f"{pat.upper()} detected — irreversible structural change"
    if lowered.startswith("update") and "where" not in lowered:
        return "danger", "UPDATE without WHERE — affects all rows"
    if lowered.startswith(("select",)):
        return "safe", "Read-only query"
    return "caution", "Write query — will run inside a transaction and roll back"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    file = request.files.get("dbfile")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    project_id = str(uuid.uuid4())[:8]
    dest_path = os.path.join(UPLOAD_DIR, f"{project_id}.db")
    file.save(dest_path)

    try:
        schema = extract_schema(dest_path)
    except Exception as e:
        return jsonify({"error": f"Could not read database: {e}"}), 400

    remember(project_id, "schema", {
        "tables": schema,
        "summary": f"Uploaded DB with {len(schema)} tables"
    })

    return jsonify({
        "project_id": project_id,
        "schema": schema
    })


@app.route("/api/run", methods=["POST"])
def run_query():
    data = request.get_json()
    project_id = data.get("project_id")
    sql = data.get("sql", "").strip()

    if not project_id or not sql:
        return jsonify({"error": "Missing project_id or sql"}), 400

    db_path = os.path.join(UPLOAD_DIR, f"{project_id}.db")
    if not os.path.exists(db_path):
        return jsonify({"error": "Unknown project. Upload a database first."}), 404

    risk_level, risk_reason = classify_risk(sql)

    # Work on a temp copy so the original is NEVER touched
    temp_path = db_path + f".tmp{int(time.time()*1000)}"
    shutil.copy(db_path, temp_path)

    before_schema = extract_schema(temp_path)

    conn = sqlite3.connect(temp_path)
    cur = conn.cursor()
    result = {"columns": [], "rows": [], "rowcount": 0}
    error = None

    try:
        cur.execute("BEGIN")
        cur.execute(sql)
        if cur.description:
            result["columns"] = [d[0] for d in cur.description]
            result["rows"] = cur.fetchall()
        result["rowcount"] = cur.rowcount
        conn.rollback()  # ALWAYS roll back — this is a preview tool
    except Exception as e:
        error = str(e)
        conn.rollback()
    finally:
        conn.close()
        os.remove(temp_path)

    if error:
        remember(project_id, "error", {
            "sql": sql, "error": error,
            "summary": f"Error running query: {error[:80]}"
        })
        return jsonify({
            "error": error,
            "risk": {"level": risk_level, "reason": risk_reason}
        }), 200

    remember(project_id, "query", {
        "sql": sql,
        "risk": risk_level,
        "rowcount": result["rowcount"],
        "summary": f"Ran [{risk_level}] query affecting {result['rowcount']} rows"
    })

    return jsonify({
        "result": {
            "columns": result["columns"],
            "rows": result["rows"],
            "rowcount": result["rowcount"]
        },
        "risk": {"level": risk_level, "reason": risk_reason},
        "note": "Executed inside a transaction and rolled back — your original database is untouched."
    })


@app.route("/api/memory/<project_id>")
def get_memory(project_id):
    return jsonify(recall(project_id))


def rule_based_answer(mem, question):
    timeline = mem.get("timeline", [])
    if not timeline:
        return "I don't have any memory for this project yet. Upload a database and run a query first."

    if "last" in question or "recent" in question or "earlier" in question:
        recent = timeline[-5:]
        lines = [f"- {e['kind']}: {e['summary']}" for e in recent]
        return "Here's what I remember from this project's recent history:\n" + "\n".join(lines)
    elif "error" in question:
        errors = mem.get("errors", [])
        if not errors:
            return "No errors have been recorded for this project."
        return "Recorded errors:\n" + "\n".join(f"- {e['sql']} → {e['error']}" for e in errors[-5:])
    elif "table" in question or "schema" in question:
        schema = mem.get("schema")
        if not schema:
            return "No schema on record yet."
        tables = schema.get("tables", {})
        return "Tables I remember: " + ", ".join(tables.keys())
    else:
        return (f"This project has {len(mem.get('queries', []))} queries and "
                f"{len(mem.get('errors', []))} errors recorded across all sessions. "
                f"Ask me about 'recent activity', 'errors', or 'tables'.")


def build_memory_context(mem):
    lines = []
    schema = mem.get("schema")
    if schema:
        for table, info in schema.get("tables", {}).items():
            cols = ", ".join(c["name"] for c in info["columns"])
            lines.append(f"Table {table} ({info['row_count']} rows): columns [{cols}]")

    queries = mem.get("queries", [])
    if queries:
        lines.append("\nQuery history (most recent last):")
        for q in queries[-15:]:
            lines.append(f"- [{q['risk']}] {q['sql']}  (rows affected: {q['rowcount']})")

    errors = mem.get("errors", [])
    if errors:
        lines.append("\nErrors encountered:")
        for e in errors[-10:]:
            lines.append(f"- {e['sql']} -> {e['error']}")

    return "\n".join(lines) if lines else "No history recorded yet."


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Memory-aware Q&A. Uses Gemini if GEMINI_API_KEY is configured;
    falls back to a rule-based answer if the key is missing or the
    API call fails, so a demo never breaks on a network/quota issue.
    """
    data = request.get_json()
    project_id = data.get("project_id")
    question = data.get("question", "")

    mem = recall(project_id)

    if gemini_client and mem.get("timeline"):
        try:
            context = build_memory_context(mem)
            prompt = (
                "You are a database assistant with persistent memory of a user's "
                "SQL session history. Answer the user's question using ONLY the "
                "context below. Be concise (2-4 sentences). If the answer isn't "
                "in the context, say you don't have that information.\n\n"
                f"MEMORY CONTEXT:\n{context}\n\n"
                f"USER QUESTION: {question}"
            )
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            answer = response.text.strip()
            return jsonify({"answer": answer, "source": "gemini"})
        except Exception as e:
            print(f"[warn] Gemini call failed, falling back to rule-based: {e}")
            answer = rule_based_answer(mem, question.lower())
            return jsonify({"answer": answer, "source": "fallback"})

    answer = rule_based_answer(mem, question.lower())
    return jsonify({"answer": answer, "source": "fallback"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
