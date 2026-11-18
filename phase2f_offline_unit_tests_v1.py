#!/usr/bin/env python3
"""Offline validation: trusted handwritten code only; does not need the Mac repository."""
from __future__ import annotations

import json
from pathlib import Path

import phase2f_oracles_v1 as O
import phase2f_prepare_dev_suite_v1 as P
import phase2f_mutant_calibration_v1 as C


def main():
    totals = O.exhaustively_selfcheck()
    assert len(totals) == 8 and min(totals.values()) > 0
    # The fixture supplies artificial provenance ONLY for unit-testing.
    fake_provenance = {'offline_test_only_not_real_dataset_verification': True}
    inputs, labels, ib, lb = P.make_documents(fake_provenance)
    assert P.check_documents(inputs, labels) == 1024
    assert inputs['policy_and_execution_authorized'] is False
    assert labels['candidate_execution_authorized'] is False
    assert inputs['expected_values_included'] is False
    assert labels['test_inputs_sha256'] == P.digest(ib)
    inputs2, labels2, ib2, lb2 = P.make_documents(fake_provenance)
    assert ib2 == ib and lb2 == lb and inputs2 == inputs and labels2 == labels
    assert all(len(t['cases']) == 128 for t in inputs['tasks'].values())
    for task in O.ORDER:
        seen = set()
        mismatch_count = 0
        for case in inputs['tasks'][task]['cases']:
            assert 'expected' not in case and 'expected_type' not in case
            key = json.dumps(case['args'], sort_keys=True)
            assert key not in seen
            seen.add(key)
            expected = O.oracle_pair(task, case['args'])
            actual = C.mutant(task, case['args'])
            mismatch_count += (type(expected) is not type(actual) or expected != actual)
        assert mismatch_count > 0, f'Mutant escaped: {task}'
    labels['tasks']['HumanEval/69'][0]['expected_json_value'] = -5000
    try:
        P.check_documents(inputs, labels)
    except AssertionError:
        pass
    else:
        raise AssertionError('Oracle evidence tampering not detected')
    inputs['tasks']['HumanEval/129']['cases'][0]['args'][0][0][0] = -99
    try:
        P.check_documents(inputs, labels2)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid development input not detected')
    print('OFFLINE UNIT TESTS PASSED')
    print('Exhaustive/cross-check cases:', sum(totals.values()))
    print('Development inputs generated and checked:', 1024)
    print('Synthetic mutants detected:', len(O.ORDER))
    print('No model-generated program, Docker, model call, or project files involved.')
    print('Actual Mac project V3 provenance integration requires a local run.')


if __name__ == '__main__':
    main()
