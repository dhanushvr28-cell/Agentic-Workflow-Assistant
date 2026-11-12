# Agentic Workflow Assistant

An AI agent that answers operations questions for an online shop by choosing and chaining tools: it queries a SQL database, searches policy documents, does exact arithmetic and creates support tickets.

One question often needs several tools. For "the customer opened order 100 and wants to return it, how much refund do they get?" the agent looks up the order, finds the refund policy, and calculates 85% of the order total.

## How it works

```
question ─► LLM decides ─► tool call ─► result back to the LLM ─► ... ─► final answer
                │
                ├─ query_database     read-only SQL over customers, products, orders, tickets
                ├─ get_order_status   one order with product, customer and days since delivery
                ├─ search_policies    semantic search over policy documents
                ├─ calculate          safe arithmetic (no eval)
                └─ create_ticket      writes a support ticket
```

The loop is written directly on the OpenAI-compatible tool-calling API, without an agent framework, so every step is visible and testable.

## What makes it reliable

- **Tool errors go back to the model.** Invalid SQL, a missing order or bad arguments are returned as an error message, with the schema where useful, so the model can correct the call.
- **Arguments are validated** against each tool's schema before anything runs.
- **The database tool cannot write.** Only a single SELECT is accepted, and the connection itself is opened read-only.
- **A step limit** stops runaway loops; the agent then gives its best answer from what it has gathered.
- **Fallback protocol.** If the provider rejects a native tool call, the agent switches to a JSON reply protocol and continues.
- **Full trace.** Every answer is stored with the tools called, their arguments and results.

## Quick start

Windows: double-click `run_all.bat` (installs packages, runs the tests and the evaluation).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # add LLM_API_KEY (Groq or Gemini free tier)
python -m agent.seed                 # create the demo database
uvicorn agent.api:app --reload       # interactive API docs at http://localhost:8000/docs
```

Then open http://localhost:8000/docs and send `POST /chat` with a body such as
`{"message": "Which loyalty tier is customer 7 in, and what discount do they get?"}`.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | Ask a question (`message`, optional `session_id` for follow-ups). Returns the answer and the tool trace |
| GET | `/sessions/{id}` | Conversation history with every tool call |
| GET | `/health` | Service status |

## Evaluation

```bash
python -m eval.run_eval      # writes eval/results.md and eval/results.json
```

22 tasks in four groups: database lookups, policy questions, multi-step tasks that combine data, policy and arithmetic, and one action task that must create a ticket with the correct priority. The expected answers are computed from the database with SQL, and the ticket task is checked against the database state, so no LLM judge is involved.

### Results

<!-- Paste the summary table from eval/results.md here. -->
_Run the evaluation and paste `eval/results.md` here._

## Design decisions

- **Why no agent framework?** The whole loop is about 150 lines. Writing it directly makes error handling, the step limit and the fallback protocol explicit, and it can be unit-tested with a scripted model.
- **Why SQL as a tool instead of one function per question?** A single read-only SQL tool covers counts, joins and rankings that fixed functions cannot anticipate. The risk is handled by the SELECT-only check and the read-only connection.
- **Why a calculator tool?** Language models make arithmetic mistakes; percentages and totals are computed exactly.
- **Why programmatic checks?** Success is measured against values from the database, which is reproducible and cheaper than LLM judging.
- **Limitations:** the data is synthetic and small; the checks look for the key number or fact in the answer, not the quality of the wording; ticket creation has no human approval step.

## Tests

```bash
pytest -q
```

Tests run offline with a scripted model and a fake embedder.
