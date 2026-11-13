"""Restricted Docker evaluator, with bounded output and isolated per-case children.

This reduces accidental interference and ordinary resource abuse; it is NOT a
security boundary against a determined malicious Python attacker. Do not run
hostile code without a hardened isolated worker/VM under trusted supervision.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import subprocess
import time
from uuid import uuid4

IMAGE = ("python:3.11-slim@sha256:"
         "07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535")
CASE_TIMEOUT = 3
MAX_CODE_BYTES = 256_000
MAX_CASES_PER_BATCH = 20
MAX_BATCH_OUTPUT = 2_000_000

# Child's fd 1 and 2 are suppressed while candidate code runs. Only this
# harness emits structured JSON after restoring a clean saved descriptor.
# This blocks ordinary print/os.write spoofing, not arbitrary malicious tampering.
CHILD = r'''
import json, os, sys, resource
payload=json.load(sys.stdin)
resource.setrlimit(resource.RLIMIT_FSIZE,(131072,131072))
record={"status":"exception","error_type":"UnknownError"}
saved_fd=os.dup(1)
saved_err=os.dup(2)
null_fd=os.open("/dev/null",os.O_WRONLY)
coverage_lines=set()
def _type_tree(value,depth=0):
    kind=type(value).__name__
    if depth>=6:
        return {"kind":kind,"truncated":True}
    if type(value) in (list,tuple):
        items=[_type_tree(x,depth+1) for x in value[:128]]
        return {"kind":kind,"items":items,"length":len(value),
                "truncated":len(value)>128}
    return {"kind":kind}
def tracer(frame,event,arg):
    if event=="line" and frame.f_code.co_filename=="<candidate>":
        coverage_lines.add(frame.f_lineno)
    return tracer
try:
    os.dup2(null_fd,1)
    os.dup2(null_fd,2)
    ns={"__name__":"candidate_module"}
    if payload.get("coverage",False):
        sys.settrace(tracer)
    try:
        exec(compile(payload["code"],"<candidate>","exec"),ns)
        if payload["interface"]=="leetcode_method" and payload["entry_point"] not in ns:
            fn=getattr(ns["Solution"](),payload["entry_point"])
        else:
            fn=ns[payload["entry_point"]]
        value=fn(*payload["args"])
        as_json=json.dumps(value,allow_nan=False)
        record={"status":"ok","value":json.loads(as_json),"type":type(value).__name__}
        if payload.get("describe_types",False):
            record["type_tree"]=_type_tree(value)
    finally:
        sys.settrace(None)
except BaseException as exc:
    record={"status":"exception","error_type":type(exc).__name__,"error":str(exc)[:300]}
finally:
    try:
        # Flush Python-level buffered writes while stdout/stderr still point
        # to /dev/null. Otherwise pending print() output could appear AFTER
        # restoring the trusted JSON response descriptor.
        try: sys.stdout.flush()
        except BaseException: pass
        try: sys.stderr.flush()
        except BaseException: pass
        os.dup2(saved_fd,1)
        os.dup2(saved_err,2)
    except OSError:
        pass
    for fd in (null_fd,saved_fd,saved_err):
        try: os.close(fd)
        except OSError: pass
if payload.get("coverage",False):
    record["line_coverage"]=sorted(coverage_lines)
try:
    raw=json.dumps(record,ensure_ascii=False,allow_nan=False).encode("utf-8")
except BaseException:
    raw=b'{"status":"protocol_error"}'
if len(raw)>60000:
    raw=b'{"status":"output_limit"}'
os.write(1,raw)
'''

# Outer process cannot execute submitted code: only a fresh child executes it.
# Child stdout/stderr are regular files (rather than unbounded capture pipes),
# with a file-size cap; the outer process reports a single JSON array.
CONTAINER = r'''
import json, resource, subprocess, sys, tempfile, time, os
payload=json.load(sys.stdin)
results=[]
env={"PATH":"/usr/local/bin:/usr/bin:/bin","PYTHONHASHSEED":"0","PYTHONIOENCODING":"utf-8"}
def limit_filesize():
    resource.setrlimit(resource.RLIMIT_FSIZE,(131072,131072))
for case in payload["cases"]:
    child={"code":payload["code"],"entry_point":payload["entry_point"],
           "interface":payload["interface"],"args":case["args"],
           "coverage":bool(payload.get("coverage",False)),
           "describe_types":bool(payload.get("describe_types",False))}
    started=time.perf_counter()
    with tempfile.TemporaryFile(mode="w+b") as out, tempfile.TemporaryFile(mode="w+b") as err:
        try:
            completed=subprocess.run([sys.executable,"-I","-S","-B","-c",payload["child_runner"]],
                       input=json.dumps(child).encode("utf-8"),stdout=out,stderr=err,
                       timeout=payload["case_timeout"],env=env,close_fds=True,
                       preexec_fn=limit_filesize,check=False)
            elapsed=round(time.perf_counter()-started,5)
            if completed.returncode!=0:
                result={"status":"process_error","exit_code":completed.returncode}
            else:
                out.seek(0)
                raw=out.read(65000)
                if len(raw)>60000:
                    result={"status":"output_limit"}
                else:
                    try: result=json.loads(raw)
                    except (ValueError,UnicodeDecodeError): result={"status":"invalid_output"}
                    if not isinstance(result,dict) or result.get("status") not in \
                       ("ok","exception","output_limit","protocol_error"):
                        result={"status":"invalid_output"}
        except subprocess.TimeoutExpired:
            elapsed=round(time.perf_counter()-started,5)
            result={"status":"timeout"}
        except BaseException as exc:
            elapsed=round(time.perf_counter()-started,5)
            result={"status":"runner_error","error_type":type(exc).__name__}
    result["execution_seconds"]=elapsed
    results.append(result)
print(json.dumps(results,ensure_ascii=False,separators=(",",":"),allow_nan=False))
'''


class DockerSandbox:
    def __init__(self, image: str = IMAGE, timeout: int = CASE_TIMEOUT):
        self.image = image
        self.timeout = timeout

    def ensure_ready(self) -> None:
        for command in (("docker", "info"), ("docker", "image", "inspect", self.image)):
            try:
                done = subprocess.run(command, capture_output=True, timeout=20, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"Docker unavailable: {exc}") from exc
            if done.returncode:
                raise RuntimeError("Docker is unavailable or pinned image missing. "
                                   f"Command: {' '.join(command)}. "
                                   "Pull the pinned image once before continuing.")

    def run(self, code: str, entry_point: str, interface: str, cases: list[dict],
            *, coverage: bool = False, describe_types: bool = False) -> tuple[list[dict], float]:
        if interface not in ("callable", "leetcode_method"):
            raise ValueError("Unsupported execution interface; add a dataset adapter")
        if not entry_point or not entry_point.isidentifier():
            raise ValueError("Invalid entry point")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError("Source code too large")
        if not 1 <= len(cases) <= MAX_CASES_PER_BATCH:
            raise ValueError("A Docker batch must contain 1..20 test cases")
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("args"), list):
                raise ValueError("Cases must use JSON list arguments")
        payload = {"code": code, "entry_point": entry_point, "interface": interface,
                   "cases": cases, "child_runner": CHILD, "case_timeout": self.timeout,
                   "coverage": coverage, "describe_types": describe_types}
        try:
            serialized = json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Unsupported input payload") from exc
        if len(serialized.encode("utf-8")) > 1_000_000:
            raise ValueError("Payload too large")
        container_name = "phase2d-" + uuid4().hex[:16]
        command = [
            "docker", "run", "--rm", "-i", "--name", container_name, "--pull=never",
            "--network=none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--pids-limit=32",
            "--memory=192m", "--memory-swap=192m", "--cpus=0.5",
            "--user=65534:65534", "--ulimit=nofile=64:64", "--ulimit=core=0",
            "--env=PYTHONHASHSEED=0", "--env=PYTHONIOENCODING=utf-8",
            self.image, "python", "-I", "-S", "-B", "-c", CONTAINER,
        ]
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, input=serialized, text=True,
                  capture_output=True, timeout=max(45, len(cases)*self.timeout + 15), check=False)
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "rm", "--force", container_name],
                           capture_output=True, timeout=20, check=False)
            raise RuntimeError("Docker batch exceeded timeout") from exc
        elapsed = time.perf_counter() - start
        if completed.returncode:
            raise RuntimeError("Docker batch failed: " + completed.stderr[-800:])
        if len(completed.stdout.encode("utf-8")) > MAX_BATCH_OUTPUT:
            raise RuntimeError("Docker response exceeded limit")
        try:
            results = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Docker response was not JSON") from exc
        if not isinstance(results, list) or len(results) != len(cases):
            raise RuntimeError("Docker response count mismatch")
        return results, elapsed
