#!/usr/bin/env python3
"""Phase 2D restricted development shortlist, PROPOSAL ONLY.

Read-only until the final, new output file is created. Never changes the split,
quarantine, task-authorization policy, source records, or candidate programs.

Usage:
    .venv/bin/python phase2d_restricted_development_eligibility_v1.py --preview
    .venv/bin/python phase2d_restricted_development_eligibility_v1.py

Only publicly available development task specifications are ranked; no solutions,
private tests, candidate outcomes, or future evaluation tasks are inspected.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from io import StringIO
from hashlib import sha256
import json
from pathlib import Path
import re

import phase2d_quarantine_guard as guard
from phase2d_global_overlap_audit import load_and_verify, get_exact_groups, strip_template

ROOT = Path(__file__).resolve().parent
BASE = Path('results/phase2d')
PINS = {
    'split_proposal': ('results/phase2d/split_resolution_proposal_v1.json',
       '0dc013b61353eae253d942e8f757ad626eeaa4b2cca569f6174737914509778c'),
    'batch4_review': ('results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json',
       '84b0e2e541a075c151e6f742bd21267b34410f6000eb8032f9019693e570d84f'),
    'batch4_development': ('results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/development_second_review_queue.csv',
       '62bc7a431991a7f401193730814d94d5bab52407a6cc27391eddac17c0924ea2'),
    'batch4_evaluation': ('results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/validation_heldout_watchlist.csv',
       '753c418bfc61b90c66d1644fa6bfa22229c4be4e85a5a8bbf1e81115b15d975b'),
    'batch4_triage': ('results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/batch4_policy_triage_summary.json',
       '10fb936babf23a99614781d56dad1719fc88085f8a630503ef7de81f927b472a'),
    'priority_adjudication': ('results/phase2d/phase2d_batch4_priority_adjudication_addendum_v1.json',
       'd5151eb052e225f9d9406d19845ada52362368e548a7abe367001cb80c50731d'),
    'remaining_adjudication': ('results/phase2d/phase2d_batch4_remaining_adjudication_addendum_v1.json',
       '0f2a793f05473919c5b6d771a56bade9b13b0a17bb4183a54f1d8a25f8d9e01b'),
}
OUTPUT = BASE / 'restricted_development_eligibility_proposal_v1.json'

# Deliberately exclude BigCodeBench from this *first* proposed executable pool:
# many tasks require I/O, network mocks, ML libraries, random state, or plots.
TARGET_BY_DATASET = {'humaneval': 12, 'mbpp': 12}
MAX_SELECTED = sum(TARGET_BY_DATASET.values())

# Conservative keyword filter for *initial screening*, not a security proof.
# Actual execution, if separately authorized, MUST use the existing Docker guard.
NONDETERMINISM_OR_IO = re.compile(
    r'\b(?:random(?:ly)?|stochastic|shuffle|download|https?|url|requests|'
    r'file(?:s|name|path)?|folder|director(?:y|ies)|filesystem|pickle|'
    r'open\s*\(|read_csv|write_csv|read_excel|savefig|plot|figure|'
    r'matplotlib|seaborn|tensorflow|keras|pytorch|torch|numpy|pandas|'
    r'database|socket|subprocess|os\.system|eval\s*\(|exec\s*\(|'
    r'current\s+(?:time|date)|time\.time|calendar|datetime|'
    r'environment\s+variable|internet|api\s+call|delete|remove\s+file)\b',
    flags=re.I,
)


def check(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def read_pinned(label):
    rel, expected = PINS[label]
    path = ROOT / rel
    if not path.is_file() and label in {'priority_adjudication', 'remaining_adjudication'}:
        alternative = ROOT / Path(rel).name
        if alternative.is_file():
            path = alternative
    check(path.is_file(), f'Missing {label}: {path}\nCopy the addendum into results/phase2d/ first.')
    raw = path.read_bytes()
    actual = sha256(raw).hexdigest()
    check(actual == expected, f'SHA-256 mismatch: {label}: expected {expected}, got {actual}')
    if path.suffix == '.csv':
        records = list(csv.DictReader(StringIO(raw.decode('utf-8-sig'))))
    else:
        records = json.loads(raw)
        check(isinstance(records, dict), f'{label}: expected JSON object')
    return records, {'path': str(path.relative_to(ROOT)), 'sha256': actual}


def task_pair(row):
    a, b = row.get('task_a'), row.get('task_b')
    check(isinstance(a, str) and bool(a) and isinstance(b, str) and bool(b) and a != b,
          f'Invalid pair: {row}')
    return tuple(sorted((a, b)))


def validate_adjudications(label, data, tasks, expected_count):
    check(data.get('execution_authorized') is False, f'{label}: permission changed')
    check(data.get('independent_human_review_completed') is False if label == 'remaining_adjudication'
          else data.get('independent_second_review_completed') is False,
          f'{label}: unexpected human-review state')
    pairs = data.get('pairs')
    check(isinstance(pairs, list) and len(pairs) == expected_count,
          f'{label}: wrong pair count')
    found = set()
    for p in pairs:
        key = task_pair(p)
        check(key not in found, f'{label}: duplicate pair {key}')
        found.add(key)
        for suffix in ('a', 'b'):
            name = p['task_' + suffix]
            expected = p.get(f'task_{suffix}_manifest_public_prompt_sha256')
            check(name in tasks and tasks[name]['public_prompt_sha256'] == expected,
                  f'{label}: task hash mismatch {name}')
        check(p.get('behavioral_equivalence_proven') is False,
              f'{label}: unexpected equivalence-proof claim')
    return found


def task_family(prompt):
    s = strip_template(prompt).lower()
    if re.search(r'\b(?:string|substring|word|palindrome|regex|parenthes|character|letter|text)\b', s):
        return 'strings_parsing'
    if re.search(r'\b(?:graph|tree|binary.search|sort|search|path|subsequence)\b', s):
        return 'algorithms'
    if re.search(r'\b(?:list|array|tuple|sequence|matrix|element|dictionary|set|index)\b', s):
        return 'collections'
    if re.search(r'\b(?:prime|integer|divisib|number|factor|sum|product|digit|geometry|area)\b', s):
        return 'numerical'
    return 'other'


def complexity_proxy(prompt):
    """A coarse *prompt-feature* label, not measured task difficulty."""
    s = strip_template(prompt).lower()
    count = len(s.split())
    challenging = ('nested', 'recurs', 'dynamic', 'optimiz', 'graph', 'tree',
                   'substring', 'permutation', 'subsequence', 'longest', 'shortest')
    if count > 100 or any(t in s for t in challenging):
        return 'higher_prompt_complexity'
    if count > 35:
        return 'medium_prompt_complexity'
    return 'lower_prompt_complexity'


def round_robin_shortlist(pool, targets):
    """Deterministic, outcome-blind selection across dataset and topic families."""
    selected = []
    by_dataset = defaultdict(lambda: defaultdict(deque))
    for p in pool:
        by_dataset[p['dataset']][p['family']].append(p)
    for ds in by_dataset:
        for family, bucket in by_dataset[ds].items():
            ordered = sorted(bucket, key=lambda x: (
                {'higher_prompt_complexity': 0, 'medium_prompt_complexity': 1,
                 'lower_prompt_complexity': 2}[x['prompt_complexity_proxy']],
                sha256(x['task_id'].encode()).hexdigest(), x['task_id']))
            by_dataset[ds][family] = deque(ordered)
    for ds, target in targets.items():
        groups = by_dataset.get(ds, {})
        for _ in range(target):
            nonempty = [(name, q) for name, q in groups.items() if q]
            if not nonempty:
                break
            # Choose the least represented family so far, deterministic ties.
            family_counts = Counter(x['family'] for x in selected if x['dataset'] == ds)
            family, q = min(nonempty, key=lambda item: (family_counts[item[0]], item[0]))
            selected.append(q.popleft())
    # If a dataset has too few safe tasks, do not fabricate a replacement.
    return selected


def build():
    manifest, existing_quarantine = guard.load_verified_policy(ROOT)
    public_tasks, verified_manifest, public_hashes = load_and_verify(ROOT)
    check(manifest == verified_manifest, 'Manifest changed between two independent loads')
    entries = manifest['tasks']
    check(manifest.get('status') == 'draft_requires_review_and_freeze',
          'Not a draft manifest; this proposal requires protocol review')
    check(len(entries) == 3333 and len(existing_quarantine) == 21,
          'Unexpected task or quarantine census')
    check(len(public_tasks) == 3333, 'Incomplete public corpus')
    docs, pins = {}, {}
    for label in PINS:
        docs[label], pins[label] = read_pinned(label)

    previous = docs['split_proposal']
    check(previous.get('execution_authorized') is False and
          previous.get('final_split_freeze_authorized') is False,
          'Earlier proposal unexpectedly claims approval')
    old_pairs = previous.get('pairwise_provisional_actions')
    check(isinstance(old_pairs, list) and len(old_pairs) == 29,
          'Expected 29 original proposal risk pairs')
    original_keys = {task_pair(p) for p in old_pairs}
    check(len(original_keys) == 29, 'Duplicate original risk pair')

    review = docs['batch4_review']
    check(review.get('record_type') ==
          'PROVISIONAL_STRATIFIED_PUBLIC_PROMPT_REVIEW_NOT_SPLIT_APPROVAL',
          'Unexpected Batch4 review kind')
    review_rows = review.get('reviews')
    check(isinstance(review_rows, list) and len(review_rows) == 81 and
          sum(review.get('verdict_counts', {}).values()) == 81,
          'Incomplete Batch4 reviewed sample')
    dev_rows = docs['batch4_development']
    eval_rows = docs['batch4_evaluation']
    check(len(dev_rows) == 21 and len(eval_rows) == 14,
          'Batch4 triage CSV counts changed')
    check(docs['batch4_triage'].get('execution_authorized') is False and
          docs['batch4_triage'].get('final_split_freeze_authorized') is False,
          'Unexpected Batch4 triage approval')

    priority_pairs = validate_adjudications(
        'priority_adjudication', docs['priority_adjudication'], entries, 14)
    remaining_pairs = validate_adjudications(
        'remaining_adjudication', docs['remaining_adjudication'], entries, 22)
    check(not (priority_pairs & remaining_pairs), 'Adjudication pair overlap')
    check({task_pair(p) for p in dev_rows}.issubset(priority_pairs | remaining_pairs),
          'Development triage pair not found in adjudications')
    check({task_pair(p) for p in eval_rows}.issubset(remaining_pairs),
          'Evaluation triage pair not found in remaining adjudication')

    # Do not silently drop unexpected task references or stale partitions.
    def validate_row(row, label):
        a, b = task_pair(row)
        check(a in entries and b in entries, f'{label}: unknown task {a}/{b}')
        for k in ('task_a', 'task_b'):
            pkey = 'partition_a' if k == 'task_a' else 'partition_b'
            if row.get(pkey) is not None:
                check(entries[row[k]]['partition'] == row[pkey],
                      f'{label}: partition changed for {row[k]}')
        return (a, b)

    # Every known original and Batch4 reviewed pair is a provisional risk lead.
    # Even pairs judged unrelated remain a conservative exclusion from the *first*
    # shortlist; this does NOT reclassify them as equivalent.
    pair_sources = defaultdict(set)
    def add_edge(pair, label):
        pair_sources[pair].add(label)
    for row in old_pairs:
        add_edge(validate_row(row, 'original proposal'), 'original_29')
    batch4_manual_keys = set()
    for row in review_rows:
        pair = validate_row(row, 'Batch4 sample')
        check(pair not in batch4_manual_keys, 'Duplicate Batch4 sample pair')
        batch4_manual_keys.add(pair)
        add_edge(pair, 'batch4_reviewed_81')
    for row in dev_rows:
        validate_row(row, 'development triage')
        task = row.get('development_task')
        check(task in entries and entries[task]['partition'] == 'development',
              f'Invalid development triage task: {task}')
        check(task in task_pair(row), f'Development task absent from pair: {task}')
        add_edge(task_pair(row), 'batch4_development_21')
    for row in eval_rows:
        pair = validate_row(row, 'evaluation triage')
        check({entries[p]['partition'] for p in pair} == {'validation', 'held_out'},
              'Evaluation triage has unexpected partitions')
        add_edge(pair, 'batch4_validation_heldout_14')
    check(set(review.get('proposed_development_task_review_holds', [])) ==
          {p['development_task'] for p in dev_rows},
          'Batch4 proposed development holds differ from verified triage CSV')

    # Existing lexical report is verified by V3 guard. Top-K lexical leads are
    # added as cautionary holds, NOT interpreted as duplicate confirmations.
    lexical = json.loads((ROOT / guard.REPORT_REL).read_text(encoding='utf-8'))
    check(lexical.get('report_type') ==
          'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION',
          'Unexpected lexical report')
    for name in ('cross_partition_review_queue', 'cross_dataset_stratified_review_queue'):
        rows = lexical.get(name)
        check(isinstance(rows, list), f'Missing lexical {name}')
        for row in rows:
            pair = validate_row(row, name)
            add_edge(pair, 'lexical_lead_unadjudicated')

    all_task_by_id = {t.task_id: t for t in public_tasks}
    for group in get_exact_groups(public_tasks):
        ids = group['task_ids']
        for idx in range(len(ids) - 1):
            add_edge(tuple(sorted((ids[idx], ids[idx + 1]))), 'exact_public_prompt_duplicate')

    # Conservative exclusion: any development task mentioned anywhere in an
    # evidence-derived overlap/lexical edge is not shortlisted.
    risk_members = set()
    graph = defaultdict(set)
    for (a, b), sources in pair_sources.items():
        risk_members.update((a, b))
        graph[a].add(b)
        graph[b].add(a)

    components = []
    visited = set()
    for start in sorted(graph):
        if start in visited:
            continue
        stack, members = [start], []
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            members.append(node)
            stack.extend(graph[node] - visited)
        if len(members) > 2:
            components.append(sorted(members))
    components.sort(key=lambda c: (-len(c), c))

    pilot = set(guard.PILOT_TASKS)
    check(pilot == {'HumanEval/0', 'HumanEval/1', 'MBPP/545'},
          'Draft pilot allowlist changed; protocol review required')
    counters = Counter()
    dataset_counters = Counter()
    eligible = []
    held_by_reason = Counter()
    risk_hold_development = set()

    for t in public_tasks:
        if t.partition != 'development':
            continue
        dataset_counters[t.dataset] += 1
        reasons = []
        if t.task_id in pilot:
            reasons.append('existing_pilot_not_new_expansion')
        if t.task_id in existing_quarantine:
            reasons.append('verified_v3_quarantine')
        if t.task_id in risk_members:
            reasons.append('in_reviewed_or_lexical_risk_graph')
            risk_hold_development.add(t.task_id)
        if t.dataset not in TARGET_BY_DATASET:
            reasons.append('bigcodebench_deferred_for_io_dependency_oracle_review')
        if NONDETERMINISM_OR_IO.search(t.prompt):
            reasons.append('static_io_nondeterminism_or_dependency_heuristic')
        if reasons:
            for reason in reasons:
                held_by_reason[reason] += 1
            continue
        counters[t.dataset] += 1
        eligible.append({
            'task_id': t.task_id,
            'dataset': t.dataset,
            'partition': t.partition,
            'public_prompt_sha256': t.normalized_hash,
            'family': task_family(t.prompt),
            'prompt_complexity_proxy': complexity_proxy(t.prompt),
            'public_specification_excerpt': strip_template(t.prompt).strip()[:360],
            'status': 'PROPOSED_FOR_HUMAN_TASK_AND_CONTRACT_REVIEW_ONLY',
            'execution_authorized': False,
        })

    shortlist = round_robin_shortlist(eligible, TARGET_BY_DATASET)
    check(len(shortlist) == len({p['task_id'] for p in shortlist}),
          'Duplicate shortlist task')
    for p in shortlist:
        task_id = p['task_id']
        check(task_id not in risk_members | set(existing_quarantine) | pilot and
              entries[task_id]['partition'] == 'development' and
              entries[task_id]['public_prompt_sha256'] == p['public_prompt_sha256'],
              f'Unsafe shortlist selection: {task_id}')
    summary = {
        'corpus_total_tasks': len(entries),
        'development_tasks': sum(x['partition'] == 'development' for x in entries.values()),
        'current_v3_quarantines': len(existing_quarantine),
        'batch4_development_tasks_flagged': len(dev_rows),
        'batch4_new_nonpilot_development_risks': len({p['development_task'] for p in dev_rows} - pilot),
        'batch4_reviewed_pairs': len(review_rows),
        'known_or_lexical_risk_edges': len(pair_sources),
        'development_tasks_in_precautionary_risk_graph': len(risk_hold_development),
        'static_prefilter_survivors_by_dataset': dict(sorted(counters.items())),
        'static_prefilter_survivors_total': len(eligible),
        'shortlist_target': MAX_SELECTED,
        'shortlist_selected': len(shortlist),
        'shortlist_by_dataset': dict(sorted(Counter(x['dataset'] for x in shortlist).items())),
        'shortlist_by_family': dict(sorted(Counter(x['family'] for x in shortlist).items())),
        'held_reason_counts_not_disjoint': dict(sorted(held_by_reason.items())),
        'temporal_pending_not_considered': sum(x['partition'] == 'held_out_temporal_pending'
                                               for x in entries.values()),
        'overlap_connected_components_more_than_two': len(components),
    }
    check(summary['development_tasks'] == 403 and
          summary['temporal_pending_not_considered'] == 1055,
          'Partition census differs from reviewed policy; stop')
    return {
        'schema_version': 1,
        'record_type': 'PHASE2D_RESTRICTED_DEVELOPMENT_ELIGIBILITY_PROPOSAL_V1_NOT_APPROVAL',
        'status': 'MANUAL_REVIEW_REQUIRED_NO_EXECUTION_OR_PARTITION_AUTHORIZATION',
        'manifest_status': manifest['status'],
        'execution_authorized': False,
        'guard_modification_authorized': False,
        'split_freeze_authorized': False,
        'manifest_modified': False,
        'quarantine_modified': False,
        'independent_human_review_completed': False,
        'source_artifact_sha256': pins,
        'verified_public_dataset_and_manifest_sha256': public_hashes,
        'summary': summary,
        'connected_overlap_risk_groups': components,
        'shortlist_for_manual_review': shortlist,
        'method': {
            'sampling_frame': 'Public task specifications with partition=development only; never held-out prompts for shortlist ranking.',
            'excluded_before_shortlisting': 'All current quarantines, all existing pilot tasks, every endpoint of all first-3 review pairs plus HE1/6, every Batch4 sampled pair and triage pair, top-k lexical leads and exact normalized public-prompt duplicates, static I/O and nondeterminism keyword hits, and all BigCodeBench tasks in initial pool.',
            'ranking': 'Deterministic family round-robin with a coarse prompt-complexity proxy and SHA-256 task-ID tie breaking. No model outcomes or hidden tests used.',
            'goal': 'At most 12 HumanEval and 12 MBPP candidate tasks for source-backed manual and task-specific oracle/sandbox feasibility review.',
        },
        'limitations': [
            'This is a proposed list of tasks to inspect, not a clean, decontaminated, or execution-approved benchmark.',
            'Lexical review queues are partial; 4607 screened lexical pairs were not all adjudicated; lexical screening misses semantically similar tasks with dissimilar wording.',
            'A static prompt keyword prefilter cannot certify safe execution, deterministic outputs, oracle adequacy, or task complexity.',
            'Some conservatively excluded reviewed pairs may in fact be distinct. Exclusion is a protocol choice, not a finding of equivalence.',
            'The 35 Batch4 equivalent/near-equivalent findings are from a selected stratified review, not a measured full-corpus duplication rate.',
            'Existing assistant adjudications are not independent blinded human reviews.',
            'LiveCodeBench temporal provenance remains unresolved; temporal-pending tasks are excluded.',
            'No held-out or validation execution, generation, model calls, or prompt-tuning authorization is implied.',
            'Even after approval, real-program generation/testing must be implemented via a separately versioned, human-reviewed guard amendment and hardened Docker validator.',
        ],
        'required_next_gate': [
            'Human supervisor reviews chosen public task signatures, domain restrictions, and overlap risk against unseen semantic duplicates.',
            'Prepare task-specific deterministic oracle and hardened sandbox plan for each approved development task; exclude tasks that require network or uncontrolled I/O.',
            'Record reviewer identity, decision rationale, task set hash, and frozen approved development subset.',
            'Separately approve and test an additive execution policy; keep existing draft guard unchanged until authorization.',
            'Never touch validation, held-out, or temporal-pending tasks during model development.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Read-only preview; no output written')
    args = parser.parse_args()
    result = build()
    print('PHASE 2D: RESTRICTED DEVELOPMENT ELIGIBILITY PROPOSAL V1')
    for key, value in result['summary'].items():
        if key in ('held_reason_counts_not_disjoint',):
            continue
        print(f'{key}: {value}')
    print('\nPROPOSED TASK IDS (NOT AUTHORIZED):')
    for item in result['shortlist_for_manual_review']:
        print(f"  {item['task_id']} | {item['family']} | {item['prompt_complexity_proxy']}")
    print('\nNO SPLIT FREEZE, NO GUARD CHANGE, NO EXECUTION AUTHORIZATION.')
    if args.preview:
        print('PREVIEW ONLY; no output written.')
        return
    encoded = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode('utf-8')
    path = ROOT / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as out:
        out.write(encoded)
    print('CREATED:', path.relative_to(ROOT))
    print('SHA256:', sha256(encoded).hexdigest())
    print('All original manifest, guard, review, and adjudication artifacts unchanged.')


if __name__ == '__main__':
    main()
