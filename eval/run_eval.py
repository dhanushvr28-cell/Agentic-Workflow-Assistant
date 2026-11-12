"""Run the agent on every evaluation task and report success rate, tool selection and cost.

Usage:  python -m eval.run_eval
Reseeds the demo database first, then writes eval/results.md and eval/results.json.
"""
import json

from agent.api import build_agent
from agent.config import get_settings
from agent.seed import seed
from eval.tasks import build_tasks


def run_tasks(agent, tasks: list[dict]) -> list[dict]:
    rows = []
    for i, task in enumerate(tasks, start=1):
        try:
            result = agent.run(task["q"])
        except Exception as exc:  # e.g. free-tier quota exhausted: report the tasks completed so far
            print(f"Stopping early at task {task['id']}: {exc}")
            break
        used = set(result.tools_used)
        row = {"id": task["id"], "question": task["q"], "answer": result.answer,
               "success": bool(task["check"](result.answer)),
               "tools_ok": all(used & group for group in task["tools"]),
               "tools_used": result.tools_used, "tool_calls": len(result.steps), "llm_calls": result.llm_calls,
               "tool_errors": sum(1 for s in result.steps if s["error"]), "stopped": result.stopped,
               "protocol": result.protocol, "latency_ms": result.latency_ms}
        rows.append(row)
        print(f"{i}/{len(tasks)} {task['id']}: success={row['success']} tools_ok={row['tools_ok']} "
              f"tools={result.tools_used}", flush=True)
    return rows


def summarise(rows: list[dict]) -> dict:
    n = max(1, len(rows))
    avg = lambda key: sum(r[key] for r in rows) / n
    with_errors = [r for r in rows if r["tool_errors"]]
    return {"tasks": len(rows), "success_rate": avg("success"), "tool_selection_accuracy": avg("tools_ok"),
            "avg_tool_calls": avg("tool_calls"), "avg_llm_calls": avg("llm_calls"),
            "avg_latency_s": avg("latency_ms") / 1000,
            "tasks_with_tool_errors": len(with_errors),
            "recovered_after_tool_error": sum(1 for r in with_errors if r["success"]),
            "hit_step_limit": sum(1 for r in rows if r["stopped"] == "max_steps")}


def to_markdown(summary: dict, rows: list[dict], model: str) -> str:
    lines = [f"# Evaluation results\n\nModel: `{model}`, {summary['tasks']} tasks.\n",
             "| Metric | Value |", "|---|---|",
             f"| Task success rate | {100 * summary['success_rate']:.1f}% |",
             f"| Correct tool selection | {100 * summary['tool_selection_accuracy']:.1f}% |",
             f"| Average tool calls per task | {summary['avg_tool_calls']:.2f} |",
             f"| Average LLM calls per task | {summary['avg_llm_calls']:.2f} |",
             f"| Average time per task | {summary['avg_latency_s']:.1f} s |",
             f"| Tasks with a tool error | {summary['tasks_with_tool_errors']} "
             f"({summary['recovered_after_tool_error']} still answered correctly) |",
             f"| Tasks that hit the step limit | {summary['hit_step_limit']} |",
             "\n## Per task\n", "| Task | Success | Tools OK | Tools used |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {'yes' if r['success'] else 'NO'} | {'yes' if r['tools_ok'] else 'NO'} | "
              f"{', '.join(r['tools_used']) or '-'} |" for r in rows]
    return "\n".join(lines) + "\n"


def main():
    s = get_settings()
    seed(s.db_path, s.reference_date)
    rows = run_tasks(build_agent(s), build_tasks(s.db_path, s.reference_date))
    summary = summarise(rows)
    text = to_markdown(summary, rows, s.llm_model)
    with open("eval/results.md", "w", encoding="utf-8") as f:
        f.write(text)
    with open("eval/results.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "tasks": rows}, f, indent=2)
    print(text)


if __name__ == "__main__":
    main()
