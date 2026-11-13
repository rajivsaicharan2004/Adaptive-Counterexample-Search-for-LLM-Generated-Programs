#!/usr/bin/env python3
"""Record reproducibility metadata without exposing API keys or .env contents."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
FILES=("phase1_generator.py","phase1_advanced.py","phase2a_validator.py",
       "phase2b1_validator.py","phase2b_property.py","phase2b2_mutation.py",
       "phase2b3_differential.py","phase2b4_metamorphic.py","phase2b5_fault_benchmark.py",
       "phase2d_cli.py","phase2d_strategy_cli.py")


def version(package):
    try: return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError: return None


def main():
    digests={}
    for name in FILES:
        path=ROOT/name
        if path.is_file():
            digests[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((ROOT/"phase2d").glob("*.py")):
        digests[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        git=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,
                           text=True,timeout=8,check=False)
        commit=git.stdout.strip() if git.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):
        commit=None
    try:
        docker=subprocess.run(["docker","version","--format","{{.Client.Version}}"],
                              capture_output=True,text=True,timeout=8,check=False)
        docker_version=docker.stdout.strip() if docker.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired): docker_version=None
    from phase2d.sandbox import IMAGE
    payload={"created_utc":datetime.now(timezone.utc).isoformat(),
             "python":sys.version,"platform":platform.platform(),
             "git_commit":commit,"docker_client_version":docker_version,
             "sandbox_image":IMAGE,"source_sha256":digests,
             "package_versions":{name:version(name) for name in
                ("hypothesis","google-genai","python-dotenv","coverage","pytest")},
             "notes":["No .env or API keys are read or stored.",
                      "Pin dependency versions and the Docker image before publication.",
                      "GPU/hardware telemetry should be recorded when relevant."]}
    path=ROOT/"results/phase2d/environment.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Saved environment manifest:",path.relative_to(ROOT))
    print("Recorded",len(digests),"source checksums and",len(payload["package_versions"]),"package versions")


if __name__=="__main__":main()
