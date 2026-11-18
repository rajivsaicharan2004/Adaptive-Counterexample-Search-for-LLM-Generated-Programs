#!/usr/bin/env python3
"""Researcher-attested Phase-2F DEVELOPMENT-only candidate generator.

This writes candidate code/metadata but NEVER executes it. Model API calls
remain fail-closed until the exact 8-task V4 owner scope is explicitly attested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from uuid import uuid4

import phase1_generator as generation
import phase2f_oracles_v1 as O
import phase2f_scope_gate_v1 as gate

ROOT = Path(__file__).resolve().parent
STRATEGIES = {
    'direct': ('Use the simplest correct implementation, matching the exact required function signature.', 0.2),
    'sampling': ('Return a correct implementation, handling all documented cases.', 0.9),
    'diverse': ('Try a meaningfully different algorithm than the most obvious one, preserving the interface.', 0.8),
    'boundary': ('Prioritize boundary conditions, duplicate values, tricky inputs and off-by-one errors.', 0.65),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def current_task_prompt(task):
    path = ROOT / 'data/public/humaneval.jsonl'
    for line in path.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row.get('task_id') == task:
            prompt = row.get('prompt')
            if not isinstance(prompt, str) or sha(prompt.encode('utf-8')) != O.TASKS[task][3]:
                raise RuntimeError('Original development public prompt SHA mismatch')
            return prompt
    raise RuntimeError('Public task missing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True, choices=O.ORDER)
    parser.add_argument('--method', choices=tuple(STRATEGIES), default='direct')
    parser.add_argument('--candidates', type=int, default=2)
    parser.add_argument('--max-calls', type=int, default=3)
    parser.add_argument('--model', default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.candidates <= 20 or not 1 <= args.max_calls <= 50:
        parser.error('Candidate count 1..20; max calls 1..50')
    count = min(args.candidates, args.max_calls)
    original = current_task_prompt(args.task_id)
    strategy, temperature = STRATEGIES[args.method]
    print('TASK:', args.task_id)
    print('METHOD:', args.method)
    print('PLANNED MODEL API CALLS:', count)
    print('PROMPT SHA256:', sha(original.encode('utf-8')))
    if args.dry_run:
        print('DRY RUN; no model, candidate execution, or output files.')
        return

    scope = gate.verify_attestation('generate', args.task_id, ROOT)
    print('RESEARCHER-ATTESTED SCOPE VERIFIED:', scope['attestation_sha256'])
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    model = args.model or os.environ.get('GEMINI_MODEL') or 'gemini-3.8-flash'
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        raise RuntimeError('Set GEMINI_API_KEY or GOOGLE_API_KEY in .env')
    from google import genai
    client = genai.Client(api_key=api_key)
    started = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_id = f'{started}_{uuid4().hex[:8]}'
    folder = ROOT / 'generated' / 'phase2f' / args.task_id.replace('/', '_')
    folder.mkdir(parents=True, exist_ok=True)
    run_records = []
    for i in range(1, count + 1):
        # Revalidate the exact owner authorization BEFORE EVERY paid model call.
        gate.verify_attestation('generate', args.task_id, ROOT)
        prompt = (f'Implement the public Python programming task below.\n'
                  f'Output a complete Python module only, without markdown or explanations.\n'
                  f'Preserve the function name and signature exactly.\n'
                  f'Do not access the filesystem, network, shell or external services.\n'
                  f'Generation strategy: {strategy}\n\n{original}')
        basename = f'{run_id}_{args.method}_{i:03d}'
        (folder / (basename + '.prompt.txt')).write_text(prompt, encoding='utf-8')
        t0 = time.perf_counter()
        metadata = {
            'task_id': args.task_id, 'model': model, 'method': args.method,
            'run_id': run_id, 'attempt': i,
            'original_public_prompt_sha256': O.TASKS[args.task_id][3],
            'submitted_prompt_sha256': sha(prompt.encode('utf-8')),
            'self_attested_scope_sha256': scope['attestation_sha256'],
            'provider': 'google_genai', 'temperature': temperature,
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'source_sha256': None, 'status': 'pending',
        }
        try:
            result = generation.call_gemini(client, model, prompt, temperature, 4096)
            code = generation.strip_fence(result['text']).rstrip() + '\n'
            if not code.strip():
                raise RuntimeError('Empty code response')
            data = code.encode('utf-8')
            if len(data) > 256000:
                raise RuntimeError('Output larger than sandbox input cap')
            check = generation.static_check(code, O.TASKS[args.task_id][0])
            # Save even malformed code: syntax and missing entry points are failures
            # of generation and must not disappear from reported denominators.
            with (folder / (basename + '.py')).open('xb') as handle:
                handle.write(data)
            metadata.update(source_sha256=sha(data), status='generated',
                            syntax_ok=check['syntax_ok'],
                            entry_point_present=check['entry_point_present'],
                            usage=result.get('usage'), latency_seconds=result.get('latency_seconds'))
        except Exception as exc:
            metadata.update(status='generation_error', error_type=type(exc).__name__,
                            error_message=str(exc)[:300], latency_seconds=round(time.perf_counter()-t0, 3))
        with (folder / (basename + '.json')).open('x', encoding='utf-8') as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write('\n')
        run_records.append(metadata)
        print(basename, metadata['status'], metadata.get('syntax_ok'))
    summary = {
        'record_type': 'PHASE2F_GENERATION_RUN_V1', 'task_id': args.task_id,
        'run_id': run_id, 'method': args.method, 'model': model,
        'scope_attestation_sha256': scope['attestation_sha256'],
        'attempted_calls': len(run_records), 'records': run_records,
        'model_code_executed': False, 'development_only': True,
    }
    with (folder / (run_id + '_run_summary.json')).open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write('\n')
    print('Generation completed. Code SAVED but NEVER EXECUTED.')
    print('Folder:', folder.relative_to(ROOT))
    print('Use hardened Docker evaluation only after checking the generation evidence.')


if __name__ == '__main__':
    main()
