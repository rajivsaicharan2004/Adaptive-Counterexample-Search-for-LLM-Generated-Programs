#!/usr/bin/env python3
"""Phase 1 Gemini program generator: four generation methods. Never executes model code."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
METHODS = ("direct", "sampling", "diverse", "plan", "all")
STRATEGIES = [
    "Prefer the simplest correct, readable algorithm.",
    "Look for a meaningfully different algorithm or data structure, if appropriate.",
    "Prioritize time complexity while respecting the problem constraints.",
    "Prioritize boundary cases, duplicates, empty inputs, and robustness where relevant.",
    "Prioritize space efficiency without sacrificing correctness.",
]


def sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")[:90] or "task"


def load_problem(dataset, task_id):
    path = ROOT / "data" / "public" / f"{dataset}.jsonl"
    if not path.exists():
        path = ROOT / "data" / "public" / "problems.jsonl"
    if not path.exists():
        raise FileNotFoundError("Missing public dataset. Prepare the datasets first.")
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("dataset") != dataset:
                continue
            if task_id is None or record["task_id"] == task_id:
                return record, path
    raise ValueError(f"Problem {task_id!r} not found in {dataset}.")


def base_prompt(problem):
    entry_point = problem.get("entry_point")
    mode = (
        f"Implement the callable named {entry_point!r} with the required signature. "
        "Return a complete Python module including any required imports."
        if entry_point
        else "Follow the problem's required interface exactly. If it uses standard input/output, "
        "return a complete program that reads stdin and writes stdout."
    )
    starter = problem.get("starter_code") or ""
    main = (
        "You are implementing a Python 3 solution for the following programming task.\n"
        "Return the solution code only, without markdown, explanations, or sample invocations.\n"
        "Do not read files, access the network, or install packages.\n"
        f"{mode}\n\nProblem:\n{problem['prompt']}"
    )
    if starter.strip() and starter.strip() not in problem["prompt"]:
        main += f"\n\nStarter code / required interface:\n{starter}"
    return main


def strip_fence(text):
    text = text.strip()
    match = re.fullmatch(r"```(?:python|py)?\s*\n?(.*?)\n?```", text, flags=re.S | re.I)
    return match.group(1).strip() if match else text


def static_check(code, entry_point):
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"syntax_ok": False, "syntax_error": f"{exc.msg} (line {exc.lineno})", "entry_point_present": None}
    names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return {"syntax_ok": True, "syntax_error": None,
            "entry_point_present": (entry_point in names if entry_point else None)}


def generation_status(finish_reason, checks):
    if finish_reason != "STOP":
        return "incomplete"
    if not checks["syntax_ok"] or checks["entry_point_present"] is False:
        return "invalid"
    return "generated"


def call_gemini(client, model, prompt, temperature, max_output_tokens):
    from google.genai import types

    start = time.perf_counter()

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(
                thinking_level="LOW"
            ),
        ),
    )

    usage = getattr(response, "usage_metadata", None)
    candidates = getattr(response, "candidates", None) or []
    reason = (
        getattr(candidates[0], "finish_reason", None)
        if candidates else None
    )

    return {
        "text": response.text or "",
        "latency_seconds": round(
            time.perf_counter() - start, 3
        ),
        "temperature_requested": temperature,
        "thinking_level_requested": "LOW",
        "finish_reason": (
            getattr(reason, "value", str(reason))
            if reason is not None else None
        ),
        "usage": {
            name: getattr(usage, name, None) if usage else None
            for name in (
                "prompt_token_count",
                "candidates_token_count",
                "thoughts_token_count",
                "total_token_count",
            )
        },
    }


def write_text(path, value):
    path.write_text(value, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate research code candidates with Gemini.")
    parser.add_argument("--dataset", choices=("humaneval", "mbpp", "bigcodebench", "livecodebench"), default="humaneval")
    parser.add_argument("--task-id", help="Full task ID, e.g. HumanEval/0; default: first task in dataset")
    parser.add_argument("--method", choices=METHODS, default="all")
    parser.add_argument("--candidates", type=int, default=1, help="Candidates per non-direct method")
    parser.add_argument("--max-calls", type=int, default=5, help="Safety cap on model API requests")
    parser.add_argument("--resume", help="Resume failed candidates from an existing run directory")
    parser.add_argument("--model", help="Use the exact Gemini model ID that already worked")
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and show call count; use no API credits")
    args = parser.parse_args()
    if args.candidates < 1 or args.candidates > 20:
        parser.error("--candidates must be between 1 and 20")
    if args.max_calls < 1 or args.max_output_tokens < 1:
        parser.error("--max-calls and --max-output-tokens must be positive")

    load_dotenv(ROOT / ".env")
    model = args.model or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
    problem, dataset_path = load_problem(args.dataset, args.task_id)
    methods = ["direct", "sampling", "diverse", "plan"] if args.method == "all" else [args.method]
    problem_hash = sha256(json.dumps(problem, sort_keys=True, ensure_ascii=False))

    resumed_summary = []
    retry_candidates = []
    folder = None
    run_id = None
    if args.resume:
        if args.method == "all":
            parser.error("--resume requires one specific --method")
        folder = (ROOT / args.resume).resolve()
        runs_root = (ROOT / "generated" / "phase1").resolve()
        if folder.parent != runs_root:
            parser.error("--resume must point to a run directory under generated/phase1/")
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            parser.error(f"No manifest.json found in {folder}")
        try:
            resumed_summary = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"Cannot read resume manifest: {exc}")
        if not isinstance(resumed_summary, list):
            parser.error("Resume manifest must contain a list of candidates.")
        if not resumed_summary:
            parser.error("Resume manifest contains no candidates.")
        run_id = resumed_summary[0].get("run_id")
        for item in resumed_summary:
            if (
                item.get("run_id") != run_id
                or item.get("task_id") != problem["task_id"]
                or item.get("dataset") != args.dataset
                or item.get("problem_sha256") != problem_hash
                or item.get("model") != model
            ):
                parser.error("Resume run does not match the selected problem, dataset, or model.")
        retry_candidates = [
            (item["method"], item["candidate_index"])
            for item in resumed_summary
            if item.get("method") in methods and item.get("status") == "error"
        ]
        if not retry_candidates:
            parser.error("No failed candidates for the selected method need retrying.")
        retry_keys = set(retry_candidates)
        resumed_summary = [
            item for item in resumed_summary
            if (item.get("method"), item.get("candidate_index")) not in retry_keys
        ]
        n_calls = sum(2 if method == "plan" else 1 for method, _ in retry_candidates)
    else:
        n_calls = sum(1 if method == "direct" else 2 * args.candidates if method == "plan" else args.candidates for method in methods)

    print("Problem:", problem["task_id"])
    print("Dataset file:", dataset_path.relative_to(ROOT))
    print("Model:", model)
    print("Methods:", ", ".join(methods))
    if args.resume:
        print("Failed candidates to retry:", len(retry_candidates))
    print("Maximum planned API calls:", n_calls)
    print("Private evaluation data will NOT be accessed.")
    if args.dry_run:
        print("DRY RUN complete: zero API calls made.")
        return
    # phase2d_quarantine_guard:v1
    from phase2d_quarantine_guard import require_task_permission
    require_task_permission(ROOT, problem['task_id'], 'generate')
    if n_calls > args.max_calls:
        parser.error(f"This run requires {n_calls} calls, above --max-calls {args.max_calls}. Increase deliberately if intended.")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        parser.error("Set GEMINI_API_KEY in .env (or GOOGLE_API_KEY).")

    from google import genai
    client = genai.Client(api_key=api_key)
    if args.resume:
        summary = resumed_summary
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
        folder = ROOT / "generated" / "phase1" / f"{run_id}_{safe_name(problem['task_id'])}"
        folder.mkdir(parents=True, exist_ok=False)
        summary = []
    base = base_prompt(problem)
    candidates_to_run = (
        retry_candidates
        if args.resume
        else [
            (method, i + 1)
            for method in methods
            for i in range(1 if method == "direct" else args.candidates)
        ]
    )
    for method, candidate_index in candidates_to_run:
            i = candidate_index - 1
            label = f"{method}_{candidate_index:03d}"
            stage_logs = []
            strategy = STRATEGIES[i % len(STRATEGIES)] if method == "diverse" else None
            if method == "diverse":
                prompt = base + "\n\nAdditional algorithmic goal: " + strategy
                temperature = 0.85
            elif method == "sampling":
                prompt = base
                temperature = 1.0
            elif method == "direct":
                prompt = base
                temperature = 0.2
            else:
                prompt = base
                temperature = 0.3

            meta = {
                "run_id": run_id,
                "task_id": problem["task_id"],
                "dataset": args.dataset,
                "dataset_path": str(dataset_path.relative_to(ROOT)),
                "problem_sha256": problem_hash,
                "method": method,
                "candidate_index": candidate_index,
                "model": model,
                "strategy": strategy,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "stages": stage_logs,
            }
            code = ""
            try:
                if method == "plan":
                    plan_prompt = (
                        "Create a concise, high-level IMPLEMENTATION PLAN for this Python programming problem. "
                        "Mention the algorithm, required data structures, complexity, and important edge cases. "
                        "Do not write the solution code.\n\nProblem:\n" + problem["prompt"] + ("\n\nStarter code:\n" + str(problem.get("starter_code")) if problem.get("starter_code") else "")
                    )
                    write_text(folder / f"{label}_plan.prompt.txt", plan_prompt)
                    plan = call_gemini(client, model, plan_prompt, 0.7, args.max_output_tokens)
                    stage_logs.append({"stage": "plan", **{k: v for k, v in plan.items() if k != "text"}})
                    if plan["finish_reason"] != "STOP":
                        raise RuntimeError(
                            "Gemini plan did not finish normally: "
                            f"{plan['finish_reason']!r}"
                        )
                    if not plan["text"].strip():
                        raise RuntimeError("Gemini returned an empty plan")
                    write_text(folder / f"{label}_plan.txt", plan["text"])
                    prompt = base + "\n\nFollow this implementation plan while meeting the original specification:\n" + plan["text"]
                write_text(folder / f"{label}.prompt.txt", prompt)
                result = call_gemini(client, model, prompt, temperature, args.max_output_tokens)
                stage_logs.append({"stage": "code", **{k: v for k, v in result.items() if k != "text"}})
                code = strip_fence(result["text"])
                if not code:
                    raise RuntimeError("Gemini returned no code")
                write_text(folder / f"{label}.py", code + "\n")
                checks = static_check(code, problem.get("entry_point"))
                status = generation_status(result["finish_reason"], checks)
                meta.update(
                    status=status,
                    finish_reason=result["finish_reason"],
                    code_sha256=sha256(code),
                    **checks,
                )
                if status != "generated":
                    meta["error_message"] = (
                        f"Gemini response finish reason: {result['finish_reason']!r}"
                        if status == "incomplete"
                        else "Generated response failed syntax or interface validation"
                    )
                print(
                    f"{label}: {status} | finish_reason={result['finish_reason']} "
                    f"| syntax_ok={checks['syntax_ok']} "
                    f"| entry_point_present={checks['entry_point_present']}"
                )
            except Exception as exc:
                meta.update(status="error", error_type=type(exc).__name__, error_message=str(exc)[:500])
                print(f"{label}: ERROR {type(exc).__name__}: {str(exc)[:180]}")
            (folder / f"{label}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            summary.append(meta)
            summary.sort(key=lambda item: (item["method"], item["candidate_index"]))
    (folder / "manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nResults saved to:", folder.relative_to(ROOT))
    print("Generated:", sum(m["status"] == "generated" for m in summary), "/", len(summary))


if __name__ == "__main__":
    main()
