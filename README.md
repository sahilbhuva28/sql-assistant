# SQL Assistant — Preview. Understand. Never Break.

An AI-powered database assistant that lets you run SQL safely against a
real database and remembers your query history across sessions.

## What it does

- **Safe execution.** Upload a SQLite database and run any query — every
  query executes inside a transaction that is always rolled back, so the
  original file is never modified, no matter what you run.
- **Risk classification.** Each query is tagged `safe`, `caution`, or
  `danger` (e.g. `DELETE`/`UPDATE` with no `WHERE`, `DROP TABLE`) with a
  color-coded badge in the UI.
- **Persistent memory.** Every upload, query, and error is logged to disk,
  keyed by project. This history survives a server restart — a genuinely
  new process — not just a page refresh.
- **Memory-aware chat.** Ask questions like *"what did we do recently?"*
  or *"how are these tables related?"* and get answers grounded in that
  history. Uses the Gemini API when a key is configured, with a
  rule-based fallback if it isn't.

## Tech stack

- Backend: Python 3 + Flask
- Target database: SQLite (raw `sqlite3`, transactional execution)
- Memory store: JSON file on disk, keyed by project ID
- AI: Google Gemini (`gemini-2.5-flash`) via `google-genai`
- Frontend: HTML + Tailwind CSS (CDN) + vanilla JS, single page

## Setup

```
cd sql-assistant
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your real GEMINI_API_KEY
python3 app.py
```

Open `http://127.0.0.1:5000`, upload `test_files/sample.db` (or your own
`.db` file), and start running queries.

See `FULL_TEST_SUITE.md` for a complete set of test queries with expected
results, and a full protocol for testing the cross-session memory.

## Architecture notes

The memory layer (`remember()` / `recall()` in `app.py`, backed by
`memory.json`) is intentionally shaped the way you'd structure calls to a
graph-vector memory service:

| This build | Equivalent concept |
|---|---|
| `remember(project_id, "schema", ...)` | storing a memory entity |
| `recall(project_id)` | retrieving context for a project |
| Gemini call with memory context injected | RAG-style context-grounded generation |

That separation means the memory backend can be swapped (e.g. for a
dedicated graph-vector store) without changing the Flask routes, safety
model, or frontend.

## Current scope

Supports SQLite only. MySQL/PostgreSQL, a full knowledge-graph view, and
a multi-page UI (timeline, project switcher) are natural next steps but
are not part of this build.

## Demo script

1. Upload `sample.db` — schema panel shows `users` and `orders` tables
2. Run `DELETE FROM orders;` — red **DANGER** badge, rollback confirmed
3. Run `SELECT COUNT(*) FROM orders;` — still 5 rows, nothing was lost
4. Ask the chat: *"what did we do recently?"* — recalls the upload and both queries
5. Restart the server, reload the page, ask the same question again —
   same answer, proving memory persisted across the restart
