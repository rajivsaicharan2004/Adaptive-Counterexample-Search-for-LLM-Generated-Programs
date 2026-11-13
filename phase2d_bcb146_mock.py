#!/usr/bin/env python3
"""Offline, development-only BigCodeBench/146 simulator.

Never executes real ping commands. Run generated candidates exclusively in the
existing Phase 2D DockerSandbox, with an injected subprocess mock. The mock
accepts only `ping` commands aimed at RFC5737 TEST-NET-2 addresses in small,
independently authored development cases. Official benchmark tests and reference
solutions are never read. No hidden-test accuracy claims.

Task support is deliberately NARROW: BigCodeBench/146 only. It is not an official
BigCodeBench evaluator and cannot evaluate arbitrary BigCodeBench tasks.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import time
from uuid import uuid4

from phase2d.adapters import public_task
from phase2d.candidates import discover, static_check
from phase2d.sandbox import DockerSandbox, MAX_CASES_PER_BATCH

ROOT = Path(__file__).resolve().parent
TASK_ID = "BigCodeBench/146"
ENTRY = "task_func"
WRAPPER_ENTRY = "phase2d_bcb146_offline_entry"


def make_cases():
    """Derive cases from the publicly described CIDR/ping behavior, not official tests."""
    definitions = [
        ("single_up", "198.51.100.17/32", (1,)),
        ("single_down", "198.51.100.18/32", (0,)),
        ("two_mixed", "198.51.100.20/31", (1, 0)),
        ("two_reversed", "198.51.100.22/31", (0, 1)),
        ("four_up", "198.51.100.24/30", (1, 1, 1, 1)),
        ("four_down", "198.51.100.28/30", (0, 0, 0, 0)),
        ("four_mixed", "198.51.100.32/30", (1, 0, 0, 1)),
        ("eight_alternating", "198.51.100.40/29", (1, 0, 1, 0, 0, 1, 0, 1)),
    ]
    cases = []
    for name, cidr, bits in definitions:
        hosts = list(ipaddress.IPv4Network(cidr, strict=True))
        assert len(hosts) == len(bits)
        status = {str(ip): bool(up) for ip, up in zip(hosts, bits)}
        cases.append({"name": name, "cidr": cidr, "status": status})
    return cases


MOCK_PRELUDE = r'''
import sys as __sys
import os as __os
import re as __re
import shlex as __shlex
import types as __types
import subprocess as __real_subprocess

class Phase2DUnsupportedCommand(RuntimeError):
    pass

__phase2d_mock = __types.ModuleType("subprocess")
__phase2d_mock.CalledProcessError = __real_subprocess.CalledProcessError
__phase2d_mock.TimeoutExpired = __real_subprocess.TimeoutExpired
__phase2d_mock.CompletedProcess = __real_subprocess.CompletedProcess
__phase2d_mock.PIPE = __real_subprocess.PIPE
__phase2d_mock.STDOUT = __real_subprocess.STDOUT
__phase2d_mock.DEVNULL = __real_subprocess.DEVNULL
__phase2d_mock.list2cmdline = __real_subprocess.list2cmdline
__phase2d_state = {}
__phase2d_calls = []

def __phase2d_ping(command):
    if isinstance(command, str):
        if any(symbol in command for symbol in (";", "&&", "||", "|", ">", "<", "`", "$(")):
            raise Phase2DUnsupportedCommand("Shell operators not accepted in offline development mock")
        tokens = __shlex.split(command)
    elif isinstance(command, (list, tuple)):
        tokens = [str(t) for t in command]
    else:
        raise Phase2DUnsupportedCommand("Unsupported subprocess argument type")
    if not tokens or __os.path.basename(tokens[0]).lower() not in ("ping", "ping.exe"):
        raise Phase2DUnsupportedCommand("Only mocked ping commands are permitted")
    ip_candidates = [t for t in tokens[1:] if __re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", t)]
    if len(ip_candidates) != 1 or ip_candidates[0] not in __phase2d_state:
        raise Phase2DUnsupportedCommand("Ping must target exactly one approved simulated IP")
    ip = ip_candidates[0]
    __phase2d_calls.append(ip)
    return bool(__phase2d_state[ip])

def __phase2d_run(command, *args, **kwargs):
    if args:
        raise Phase2DUnsupportedCommand("Unexpected positional subprocess parameters")
    succeeded = __phase2d_ping(command)
    ret = 0 if succeeded else 1
    output = b"mock ping success" if succeeded else b""
    if kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding"):
        output = output.decode("utf-8")
    if not succeeded and kwargs.get("check"):
        raise __real_subprocess.CalledProcessError(ret, command, output=output)
    return __real_subprocess.CompletedProcess(command, ret, stdout=output, stderr=b"")

def __phase2d_check_output(command, *args, **kwargs):
    result = __phase2d_run(command, *args, **kwargs)
    if result.returncode:
        raise __real_subprocess.CalledProcessError(result.returncode, command, output=result.stdout)
    return result.stdout

def __phase2d_check_call(command, *args, **kwargs):
    __phase2d_run(command, *args, check=True, **kwargs)
    return 0

def __phase2d_call(command, *args, **kwargs):
    return __phase2d_run(command, *args, **kwargs).returncode

def __phase2d_forbid(*args, **kwargs):
    raise Phase2DUnsupportedCommand("Unsupported external process API in offline development mock")

__phase2d_mock.run = __phase2d_run
__phase2d_mock.check_output = __phase2d_check_output
__phase2d_mock.check_call = __phase2d_check_call
__phase2d_mock.call = __phase2d_call
__phase2d_mock.Popen = __phase2d_forbid
__phase2d_mock.getoutput = __phase2d_forbid
__phase2d_mock.getstatusoutput = __phase2d_forbid
__sys.modules["subprocess"] = __phase2d_mock
__os.system = __phase2d_forbid
__os.popen = __phase2d_forbid
'''

WRAPPER = r'''
def phase2d_bcb146_offline_entry(ip_range, approved_ping_status):
    __phase2d_state.clear()
    __phase2d_state.update(approved_ping_status)
    __phase2d_calls.clear()
    try:
        result = task_func(ip_range)
        return {"returned": result, "calls": list(__phase2d_calls)}
    except BaseException as exc:
        return {"raised": type(exc).__name__, "message": str(exc)[:250],
                "calls": list(__phase2d_calls)}
'''


def build_mocked_program(code: str) -> str:
    """Preserve future imports while injecting a fake subprocess before imports."""
    tree = ast.parse(code)
    prefix, body = [], []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            prefix.append(node)
        else:
            body.append(node)
    future_source = ast.unparse(ast.Module(body=prefix, type_ignores=[])) if prefix else ""
    candidate_source = ast.unparse(ast.Module(body=body, type_ignores=[]))
    return future_source + "\n" + MOCK_PRELUDE + "\n" + candidate_source + "\n" + WRAPPER


def validate_result(output: dict, case: dict) -> tuple[bool, str | None]:
    if output.get("status") != "ok":
        return False, "execution_failure"
    payload = output.get("value")
    if not isinstance(payload, dict):
        return False, "invalid_mock_response"
    if "raised" in payload:
        return False, ("unsupported_api" if payload.get("raised") == "Phase2DUnsupportedCommand"
                       else "candidate_exception")
    value = payload.get("returned")
    calls = payload.get("calls")
    if type(value) is not dict or type(calls) is not list:
        return False, "wrong_return_type"
    if not all(type(k) is str and type(v) is bool for k, v in value.items()):
        return False, "wrong_dictionary_types"
    network = ipaddress.IPv4Network(case["cidr"])
    all_ips = {str(ip) for ip in network}
    host_ips = {str(ip) for ip in network.hosts()}
    keys = set(value)
    if keys not in (all_ips, host_ips):
        return False, "wrong_ip_coverage"
    if keys != set(calls) or len(calls) != len(keys):
        return False, "missing_or_repeated_ping_calls"
    if any(value[ip] != case["status"][ip] for ip in keys):
        return False, "incorrect_ping_status"
    return True, None


def split_guard(root: Path) -> tuple[bool, str]:
    """Do not bypass a frozen evaluation split by choosing a convenient pilot."""
    path = root / "results" / "phase2d" / "splits.json"
    if not path.is_file():
        return False, "Missing task-partition manifest. Create and review one before candidate evaluation."
    doc = json.loads(path.read_text(encoding="utf-8"))
    task = doc.get("tasks", {}).get(TASK_ID)
    partition = task.get("partition") if isinstance(task, dict) else None
    if partition != "development":
        return False, f"{TASK_ID} is assigned {partition!r}, not development; select a different development task."
    if doc.get("status") != "frozen":
        return False, "Split manifest is not frozen; finish review before running new development tasks."
    return True, "Task assigned to frozen development partition"


def main():
    parser = argparse.ArgumentParser(description="Development-only offline ping mock for BigCodeBench/146")
    parser.add_argument("--runs", nargs="+", help="Phase 1 generated run directories")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_CASES_PER_BATCH:
        parser.error("Invalid Docker batch size")
    spec = public_task(ROOT, "bigcodebench", TASK_ID)
    if spec.entry_point != ENTRY or spec.interface != "callable":
        parser.error("Public task interface has changed; this adapter needs review")
    cases = make_cases()
    allowed, message = split_guard(ROOT)
    print(f"Task: {TASK_ID} | function: {ENTRY} | offline simulated ping cases: {len(cases)}")
    print("Split policy:", message)
    candidates = discover(ROOT, args.runs, TASK_ID) if args.runs else []
    print("Candidate files:", len(candidates))
    for item in candidates:
        print(" -", item.path.relative_to(ROOT))
    if args.dry_run:
        print("DRY RUN: No Docker, model calls, network, private tests, or official evaluation")
        return
    if not allowed:
        parser.error(message)
    if not candidates:
        parser.error("Supply --runs with at least one Phase 1 candidate")
    sandbox = DockerSandbox()
    sandbox.ensure_ready()
    results = []
    total = Counter()
    started = time.perf_counter()
    for item in candidates:
        record = {"candidate": str(item.path.relative_to(ROOT)), "method": item.method,
                  "code_sha256": item.sha256}
        valid, reason = static_check(item.code, ENTRY, "callable")
        if not valid:
            record.update(status="static_error", error=reason)
            results.append(record)
            continue
        try:
            source = build_mocked_program(item.code)
            observed = []
            for pos in range(0, len(cases), args.batch_size):
                batch = cases[pos:pos + args.batch_size]
                response, duration = sandbox.run(
                    source, WRAPPER_ENTRY, "callable",
                    [{"args": [case["cidr"], case["status"]]} for case in batch]
                )
                observed.extend(response)
            checks = []
            for case, got in zip(cases, observed):
                passed, reason = validate_result(got, case)
                checks.append({"case": case["name"], "cidr": case["cidr"],
                               "passed": passed, "failure_type": reason, "actual": got})
            record.update(status="evaluated", passed=sum(c["passed"] for c in checks),
                          total=len(checks), failures=dict(Counter(c["failure_type"]
                              for c in checks if not c["passed"])), checks=checks)
            total.update({"candidate_executions": len(checks),
                          "passed_candidate_checks": record["passed"]})
        except (ValueError, OSError, RuntimeError, SyntaxError) as exc:
            record.update(status="infrastructure_error", error=str(exc)[:400])
        results.append(record)
        print(item.path.name, record["status"],
              (f"{record.get('passed')}/{record.get('total')}" if record["status"] == "evaluated"
               else record.get("error")))
    target = ROOT / "results" / "phase2d"
    target.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    path = target / ("BigCodeBench_146_offline_mock_" + tag + ".json")
    report = {"task_id": TASK_ID, "suite": "offline_simulated_ping_development",
              "official_or_held_out": False, "mocked_external_behavior": True,
              "split_policy": message, "case_count": len(cases),
              "candidate_count": len(candidates), "cost": dict(total),
              "elapsed_seconds": round(time.perf_counter() - started, 3),
              "sandbox_image": sandbox.image, "cases": cases, "results": results}
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("Saved:", path.relative_to(ROOT))
    print("Development-only mocked behavior. NOT an official BigCodeBench score.")


if __name__ == "__main__":
    main()
