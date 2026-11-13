"""One candidate registry for all eight Phase 1 generation techniques."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import ast
import json
import re
from .models import METHODS, sha256_text

PATTERN = re.compile(r"^(" + "|".join(METHODS) + r")_\d{3}\.py$")
MAX_CODE_BYTES = 256_000


@dataclass(frozen=True)
class Candidate:
    path: Path
    task_id: str
    method: str
    code: str
    sha256: str
    metadata: dict


def discover(root: Path, run_dirs: list[str], task_id: str,
             *, include_diagnostics: bool = False) -> list[Candidate]:
    if not run_dirs:
        raise ValueError("Specify one or more generated/phase1 run directories")
    allowed_root = (root / "generated" / "phase1").resolve()
    found = []
    seen = set()
    for raw in run_dirs:
        unresolved = Path(raw).expanduser()
        unresolved = unresolved if unresolved.is_absolute() else root / unresolved
        if unresolved.is_symlink():
            raise ValueError("Symlinked run directory rejected")
        folder = unresolved.resolve()
        if not folder.is_dir() or not folder.is_relative_to(allowed_root):
            raise ValueError(f"Run directory must be under {allowed_root}: {raw}")
        for path in sorted(folder.iterdir()):
            if not PATTERN.fullmatch(path.name):
                continue
            meta_path = path.with_suffix(".json")
            if (path.is_symlink() or meta_path.is_symlink() or not path.is_file()
                    or not meta_path.is_file()):
                raise ValueError("Candidate file/metadata missing or unsafe: " + str(path))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("task_id") != task_id:
                raise ValueError(f"Wrong task ID in metadata {meta_path}")
            if meta.get("status") not in ("generated", None):
                continue
            diagnostic = bool(meta.get("diagnostic_only") or
                              meta.get("source") == "synthetic_fault_injection" or
                              "diagnostic" in folder.name.lower())
            if diagnostic and not include_diagnostics:
                continue
            code_raw = path.read_bytes()
            if len(code_raw) > MAX_CODE_BYTES:
                raise ValueError(f"Candidate exceeds {MAX_CODE_BYTES} bytes: {path}")
            code = code_raw.decode("utf-8")
            digest = sha256_text(code.rstrip("\n"))
            # Source hash is checked against metadata only when available and
            # when the source's original normalization is known. The legacy
            # generator hashes before writing the trailing newline.
            if meta.get("code_sha256") and meta["code_sha256"] not in (
                    sha256_text(code), digest):
                raise ValueError(f"Candidate source checksum mismatch: {path}")
            if path in seen:
                continue
            seen.add(path)
            found.append(Candidate(path, task_id, path.name.split("_", 1)[0],
                                   code, sha256_text(code), meta))
    if not found:
        raise ValueError("No eligible Phase 1 candidate files found")
    return found


def static_check(code: str, entry: str | None, interface: str) -> tuple[bool, str | None]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax_error: {exc.msg} at line {exc.lineno}"
    funcs = {node.name for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if interface == "leetcode_method":
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Solution"]
        has_method = any(any(isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == entry
                                 for fn in cls.body) for cls in classes)
        if entry not in funcs and not has_method:
            return False, "missing_callable_or_Solution_method"
    elif entry and entry not in funcs:
        return False, "missing_top_level_function"
    return True, None
