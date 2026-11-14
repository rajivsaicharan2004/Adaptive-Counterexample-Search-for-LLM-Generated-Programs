"""Self-contained synthetic fixture for v1/v2 guard regression tests.

No benchmark tests or generated model code are used.
"""
import hashlib
import json
from pathlib import Path

from phase2d_global_overlap_audit import DATASETS, normalized_prompt, sha256_file
from phase2d_record_manual_overlap_batch2 import PAIRS, build, create_new, REPORT_REL, BATCH1_REL, BATCH2_REL

SIX = (
    ('MBPP/758','MBPP/779','validation'),
    ('MBPP/817','MBPP/883','held_out'),
    ('MBPP/931','MBPP/935','held_out'),
    ('MBPP/607','MBPP/534','validation'),
    ('MBPP/415','MBPP/922','held_out'),
    ('BigCodeBench/894','BigCodeBench/895','held_out'),
)


def dump_json(path: Path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def make_fixture(root: Path):
    roots={'humaneval':[],'mbpp':[],'bigcodebench':[],'livecodebench':[]}
    manifest={}
    def add(task_id,partition,prompt,entry_point='task_func'):
        dataset=('bigcodebench' if task_id.startswith('BigCodeBench/') else
                 'mbpp' if task_id.startswith('MBPP/') else
                 'humaneval' if task_id.startswith('HumanEval/') else 'livecodebench')
        assert task_id not in manifest,task_id
        roots[dataset].append(dict(dataset=dataset,task_id=task_id,prompt=prompt,entry_point=entry_point))
        manifest[task_id]=dict(dataset=dataset,partition=partition,
                               public_prompt_sha256=hashlib.sha256(normalized_prompt(prompt).encode()).hexdigest())
    for held,dev,held_part in SIX:
        add(held,held_part,'Synthetic older prompt '+held)
        add(dev,'development','Synthetic partner prompt '+dev)
    for p in PAIRS:
        add(p['a'],p['pa'],p['a_text']+' synthetic fixture',p['ea'])
        add(p['b'],p['pb'],p['b_text']+' synthetic fixture',p['eb'])
    for task_id in ('HumanEval/0','HumanEval/1','MBPP/545','BigCodeBench/854'):
        add(task_id,'development','Synthetic pilot '+task_id)
    add('HumanEval/10','held_out','Synthetic heldout')
    while len(manifest)<3333:
        i=len(manifest)
        dataset=DATASETS[i%4]
        prefix={'humaneval':'HumanEval','mbpp':'MBPP','bigcodebench':'BigCodeBench','livecodebench':'LiveCodeBench'}[dataset]
        add(f'{prefix}/synthetic_{i}','held_out',f'Synthetic unrelated prompt {i}')
    base=root/'data/public'
    base.mkdir(parents=True,exist_ok=True)
    for dataset,rows in roots.items():
        (base/f'{dataset}.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
    splits=root/'results/phase2d/splits.json'
    dump_json(splits,dict(schema_version='2d.1',status='draft_requires_review_and_freeze',tasks=manifest))
    hashes={str(x.relative_to(root)):sha256_file(x) for x in [splits]+[base/f'{d}.jsonl' for d in DATASETS]}
    queue=[dict(task_a=p['a'],task_b=p['b'],lexical_weighted_jaccard=round(.85-.017*i,3),
                char_5gram_jaccard=round(.88-.019*i,3)) for i,p in enumerate(PAIRS)]
    report=root/REPORT_REL
    dump_json(report,dict(report_type='PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION',
                          all_public_task_count=3333,input_sha256=hashes,cross_partition_review_queue=queue))
    pairs=[]
    for held,dev,held_part in SIX:
        pairs.append(dict(task_a=held,task_b=dev,partition_a=held_part,partition_b='development',
                          proposed_quarantine_task=dev,
                          proposed_action='quarantine_development_partner_pending_group_split_decision',
                          review_status='provisional_public_specification_review'))
    first=root/BATCH1_REL
    dump_json(first,dict(schema_version=1,
                        record_type='PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_REVIEW_NOT_PARTITION_APPROVAL',
                        manifest_status_at_review='draft_requires_review_and_freeze',
                        input_sha256=hashes,lexical_report_path=str(REPORT_REL),
                        lexical_report_sha256=sha256_file(report),
                        reviewed_pair_count=6,pairs=pairs,
                        quarantine=dict(status='proposed_not_enforced',
                                        development_task_ids=sorted(p['proposed_quarantine_task'] for p in pairs)),
                        execution_authorized=False,final_split_freeze_authorized=False))
    second=root/BATCH2_REL
    create_new(second,build(root))
    return splits,first,report
