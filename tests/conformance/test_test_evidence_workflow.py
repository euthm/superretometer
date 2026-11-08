"""Issue #18: observable positive/negative controls, not hand-edited PASS data."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cognitive_harness.evidence import (EvidenceError, Target, evaluate, export_bundle,
                                        import_receipt, record, verify)
from cognitive_harness.evidence.capture import parse_results
from cognitive_harness.evidence.contracts import canonical, load, sha, write
from cognitive_harness.storage.inmemory import InMemoryStorage

RUNNER = Path(__file__).parents[2] / 'examples/test_evidence/fixture_runner.py'
GATES = ('provenance', 'scope', 'worktree', 'test', 'falsifiability', 'dependency', 'freshness')


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    git('init', '-q')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Public fixture')
    git('remote', 'add', 'origin', 'https://example.invalid/public/fixture.git')
    (repo / 'runner.py').write_bytes(RUNNER.read_bytes())
    (repo / 'fixture.lock').write_text('fixture-version=1\n')
    git('add', '.')
    git('commit', '-qm', 'Public fixture')
    profile = {
        'repo': str(repo), 'source_paths': ['runner.py'], 'lockfiles': ['fixture.lock'],
        'archive': {'path': str(tmp_path / 'archive'), 'locator': 'fixture-archive://retained-tests', 'retention': 'Keep until explicit operator removal'},
        'claim': {'title': 'Eight synthetic assertions pass', 'scope': 'Public fixture only; no application parity claim',
                  'declared_remote': 'https://example.invalid/public/fixture.git', 'requested_commit': None,
                  'falsifier': 'Any failed/skipped/missing assertion or different tested revision invalidates this scoped claim'},
        'acceptance': {'expected_executed': 8, 'required_zero_failures': True, 'no_skips': True,
                       'required_test_ids': [f'fixture-{i}' for i in range(8)]},
        'parser': {'kind': 'counts-json/v1', 'report': 'results.json'},
        'environment': {'tools': {'python': [sys.executable, '--version']}, 'services': {},
                        'exclusions': ['Synthetic fixture; no database, networking, independent observer or service validation']},
        'timeout_seconds': 10,
    }
    target = Target('public-fixture', tmp_path / 'target', {'https://example.invalid/public/fixture.git': repo})
    return repo, profile, target


def run_fixture(profile):
    return record(profile, [sys.executable, '{repo}/runner.py', '{output}'])


def test_positive_and_isolated_controls_portable_after_restart(setup, tmp_path):
    repo, p, target = setup
    run = run_fixture(p)
    assert run['capture']['state'] == 'complete'
    assert run['acceptance']['status'] == 'pass'
    receipt = Path(run['receipt'])
    original = receipt.read_bytes()
    first = import_receipt(receipt, target)
    # New target/process state reconstructs only the explicitly persisted snapshot.
    fresh = Target(target.id, target.root, target.repositories)
    again = import_receipt(receipt, fresh)
    assert again['status'] == 'existing'
    assert first['mapping'] == again['mapping']
    assert len(fresh.state()['imports']) == 1
    positive = evaluate(fresh, run['run_id'])
    assert all(positive['gates'][g]['status'] == 'pass' for g in GATES)
    assert positive['gates']['design_bearing'] is True
    assert positive['approved'] is True
    assert positive['warrant']['warrant_status'] == 'conditionally_warranted'
    assert positive['warrant']['independent_kos'] == []
    negative = evaluate(fresh, run['run_id'], control='commit_mismatch')
    assert negative['gates']['test']['status'] == 'block'
    assert all(negative['gates'][g]['status'] == positive['gates'][g]['status'] for g in GATES if g != 'test')
    # Reasons may embed the changed commit. Only the claim commit field changes.
    pg = load(target.root / 'evaluations' / positive['evaluation_id'] / 'graph.json')
    ng = load(target.root / 'evaluations' / negative['evaluation_id'] / 'graph.json')
    ng['nodes'][0]['content']['implementation_provenance']['commit'] = pg['nodes'][0]['content']['implementation_provenance']['commit']
    assert ng == pg
    missing = evaluate(fresh, run['run_id'], control='missing_validator')
    assert missing['gates']['test']['status'] == 'unknown'
    assert not missing['gates']['design_bearing']
    assert receipt.read_bytes() == original
    output = tmp_path / 'bundle'
    exported = export_bundle(fresh, [v['evaluation_id'] for v in (positive, negative, missing)], output)
    assert exported['receipt_sha256'] == run['receipt_sha256']
    offline = verify(output)
    assert offline['source_current'] == 'unavailable'
    assert len(offline['historical_evaluations']) == 3
    assert verify(output, repo=repo)['source_current'] == 'verified'
    # Appended evaluations never overwrite historical bytes.
    old = (target.root / 'evaluations' / positive['evaluation_id'] / 'evaluation.json').read_bytes()
    (repo / 'runner.py').write_text('source drift\n')
    changed = evaluate(fresh, run['run_id'])
    assert not changed['approved']
    assert changed['gates']['freshness']['status'] == 'block'
    assert (target.root / 'evaluations' / positive['evaluation_id'] / 'evaluation.json').read_bytes() == old
    # A fresh bare InMemoryStorage never pretends it persisted a previous run.
    assert InMemoryStorage().get_ko(first['mapping']['claim']['ch_id']) is None


@pytest.mark.parametrize('mode', ['failure', 'timeout', 'not_run', 'unknown'])
def test_execution_failures_and_unknown_are_retained(setup, mode):
    _, p, target = setup
    if mode == 'failure':
        argv = [sys.executable, '-c', 'raise SystemExit(7)']
    elif mode == 'timeout':
        p['timeout_seconds'] = 0.05
        argv = [sys.executable, '-c', 'import time; time.sleep(5)']
    elif mode == 'not_run':
        argv = ['/no/such/command']
    else:
        p['parser'] = {'kind': 'unknown/v1', 'report': None}
        argv = [sys.executable, '-c', 'print("no structured counts")']
    result = record(p, argv)
    checked = verify(result['receipt'])
    assert checked['acceptance']['status'] != 'pass'
    body = load(Path(result['receipt']))
    assert body['tests']['counts']['executed'] is None
    assert body['execution']['exit_code'] == (7 if mode == 'failure' else 0 if mode == 'unknown' else None if mode == 'not_run' else -9)
    import_receipt(result['receipt'], target)
    assert not evaluate(target, result['run_id'])['approved']


@pytest.mark.parametrize('mode', ['dirty', 'untracked', 'missing', 'mutation', 'lock_mutation'])
def test_code_observations_do_not_invent_clean_state(setup, mode):
    repo, p, target = setup
    argv = [sys.executable, '{repo}/runner.py', '{output}']
    if mode == 'dirty':
        (repo / 'runner.py').write_bytes((repo / 'runner.py').read_bytes() + b'\n# dirty\n')
    elif mode == 'untracked':
        (repo / 'new-input.txt').write_text('relevant untracked input')
    elif mode == 'missing':
        p['source_paths'].append('missing.py')
    else:
        name = 'runner.py' if mode == 'mutation' else 'fixture.lock'
        argv = [sys.executable, '-c', f"from pathlib import Path; Path('{name}').write_text('changed')"]
    result = record(p, argv)
    run = load(Path(result['receipt']))
    if mode in ('dirty', 'untracked'):
        assert not run['code']['before']['clean']
        assert run['code']['before']['diff_sha256']
    else:
        assert run['capture']['state'] == 'incomplete'
    import_receipt(result['receipt'], target)
    evaluated = evaluate(target, result['run_id'])
    assert not evaluated['approved']
    if mode in ('dirty', 'untracked'):
        assert evaluated['gates']['worktree']['status'] == 'unknown'


def test_conflicting_identity_and_partial_import_are_not_accepted(setup, monkeypatch):
    _, p, target = setup
    result = run_fixture(p)
    receipt = Path(result['receipt'])
    first = import_receipt(receipt, target)
    original = receipt.read_bytes()
    run = load(receipt)
    run['claim']['title'] = 'Different claim reusing run identity'
    receipt.write_bytes(canonical(run))
    with pytest.raises(EvidenceError, match='Run ID conflict'):
        import_receipt(receipt, target)
    receipt.write_bytes(original)
    another = run_fixture(p)
    before = (target.root / 'imports.json').read_bytes()
    monkeypatch.setattr(InMemoryStorage, 'create_relation', lambda *args: False)
    with pytest.raises(EvidenceError, match='Incomplete import'):
        import_receipt(another['receipt'], target)
    assert (target.root / 'imports.json').read_bytes() == before
    assert first['mapping']


def test_receipt_bundle_tampering_and_missing_files(setup, tmp_path):
    _, p, target = setup
    result = run_fixture(p)
    receipt = Path(result['receipt'])
    import_receipt(receipt, target)
    evaluation = evaluate(target, result['run_id'])
    output = tmp_path / 'bundle'
    export_bundle(target, [evaluation['evaluation_id']], output)
    gates = output / 'evaluations' / evaluation['evaluation_id'] / 'gates.json'
    gates.write_bytes(gates.read_bytes() + b' ')
    with pytest.raises(EvidenceError, match='digest mismatch'):
        verify(output)
    receipt.parent.joinpath('logs/stdout.log').unlink()
    with pytest.raises(EvidenceError, match='Missing regular file'):
        verify(receipt)


@pytest.mark.parametrize('bad', ['../escape', '/absolute', 'a/../x', 'a\\x', 'C:/x', './x', '.git/config'])
def test_unsafe_declared_paths_rejected_before_execution(setup, bad):
    _, p, _ = setup
    p['source_paths'] = [bad]
    with pytest.raises(EvidenceError):
        run_fixture(p)


def test_symlink_and_unbound_bundle_file_rejected(setup, tmp_path):
    repo, p, _ = setup
    (repo / 'link').symlink_to(repo / 'runner.py')
    p['source_paths'] = ['link']
    run = run_fixture(p)
    assert run['capture']['state'] == 'incomplete'
    root = Path(run['receipt']).parent
    (root / 'unbound').write_text('not bound to a receipt')
    with pytest.raises(EvidenceError, match='unbound files'):
        verify(root)
    (root / 'unbound').unlink()
    (root / 'evil').symlink_to(repo / 'runner.py')
    with pytest.raises(EvidenceError, match='symlinks'):
        verify(root)


def test_schema_algorithm_versions_and_unknown_fields_rejected(setup):
    _, p, _ = setup
    result = run_fixture(p)
    path = Path(result['receipt'])
    baseline = load(path)
    for keys, value in [(('schema_version',), 'test-run/v999'), (('code', 'digest_algorithm'), 'guess/v999'), (('extra',), 'unknown')]:
        run = copy.deepcopy(baseline)
        parent = run
        for key in keys[:-1]:
            parent = parent[key]
        parent[keys[-1]] = value
        path.write_bytes(canonical(run))
        with pytest.raises(EvidenceError, match='Invalid test-run'):
            verify(path)


def test_redaction_provenance_and_remote_credential_removal(setup, monkeypatch):
    repo, p, _ = setup
    secret = 'test-only-sensitive-value'
    monkeypatch.setenv('TEST_CAPTURE_SECRET', secret)
    p['redact_env'] = ['TEST_CAPTURE_SECRET']
    p['parser'] = {'kind': 'unknown/v1', 'report': None}
    subprocess.check_call(['git', '-C', str(repo), 'remote', 'set-url', 'origin',
                           'https://user:password@example.invalid/public/fixture.git?token=hidden'])
    result = record(p, [sys.executable, '-c', 'import os; print(os.environ["TEST_CAPTURE_SECRET"])'])
    body = load(Path(result['receipt']))
    assert body['code']['remote'] == 'https://example.invalid/public/fixture.git'
    stdout = next(a for a in body['artifacts'] if a['role'] == 'stdout')
    assert stdout['transformation'] == 'redacted'
    for name in Path(result['receipt']).parent.rglob('*'):
        if name.is_file():
            assert secret.encode() not in name.read_bytes()
    with pytest.raises(EvidenceError, match='secret'):
        record(p, [sys.executable, '-c', f'print("{secret}")'])


def test_junit_counts_skips_and_untrusted_xml():
    body = b'<testsuite tests="3"><testcase name="a"/><testcase name="b"><failure/></testcase><testcase name="c"><skipped/></testcase></testsuite>'
    result = parse_results('junit/v1', body)
    assert result['counts'] == {'discovered': 3, 'executed': 2, 'passed': 1, 'failed': 1, 'skipped': 1}
    with pytest.raises(EvidenceError):
        parse_results('junit/v1', b'<!DOCTYPE testsuite><testsuite/>')
    with pytest.raises(EvidenceError):
        parse_results('counts-json/v1', b'{"schema_version":"counts/v1","counts":{},"test_ids":[]}')


def test_missing_checkout_does_not_promote_historical_pass(setup):
    _, p, target = setup
    run = run_fixture(p)
    imported = import_receipt(run['receipt'], target)
    no_checkout = Target(target.id, target.root)
    value = evaluate(no_checkout, run['run_id'])
    assert value['gates']['freshness']['status'] == 'unknown'
    assert not value['approved']


def test_target_lock_and_unsupported_backend(setup, tmp_path):
    _, _, target = setup
    with target.transaction():
        with pytest.raises(EvidenceError, match='busy'):
            with Target(target.id, target.root).transaction():
                pass
    path = tmp_path / 'target.json'
    path.write_text(json.dumps({'kind': 'implicit-memory/v1'}))
    with pytest.raises(EvidenceError, match='Unsupported target'):
        Target.from_config(path)


def test_normative_and_packaged_schema_bytes_match():
    root = Path(__file__).parents[2]
    for path in (root / 'cognitive_harness/evidence/schemas').glob('*.json'):
        assert path.read_bytes() == (root / 'spec/schemas' / path.name).read_bytes()


def test_structured_result_must_match_receipt_not_just_its_checksum(setup):
    _, p, _ = setup
    result = run_fixture(p)
    path = Path(result['receipt'])
    value = load(path)
    value['tests']['counts']['passed'] = 800
    path.write_bytes(canonical(value))
    with pytest.raises(EvidenceError, match='disagree with the structured result'):
        verify(path)


def test_invalid_profile_does_not_execute_child(setup, tmp_path):
    _, p, _ = setup
    marker = tmp_path / 'must-not-exist'
    p['acceptance']['expected_executed'] = 'eight'
    with pytest.raises(EvidenceError, match='Invalid test-capture-profile'):
        record(p, [sys.executable, '-c', f'open({str(marker)!r}, "w").write("executed")'])
    assert not marker.exists()


def test_cli_new_process_end_to_end(tmp_path):
    script = Path(__file__).parents[2] / 'examples/test_evidence/run.py'
    result = subprocess.run([sys.executable, str(script), '--output', str(tmp_path / 'example')],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value['restart_ids_preserved'] is True
    assert value['positive_approved'] is True
    assert value['negative_sha'] == 'block'
    assert value['missing_validator'] == 'unknown'
    assert value['offline_integrity'] == 'verified'


def test_ignored_declared_input_and_lost_post_state_are_incomplete(setup):
    repo, p, target = setup
    (repo / '.git/info/exclude').write_text('ignored.py\n')
    (repo / 'ignored.py').write_text('uncommitted ignored input')
    p['source_paths'].append('ignored.py')
    result = run_fixture(p)
    assert result['capture']['state'] == 'incomplete'
    import_receipt(result['receipt'], target)
    assert not evaluate(target, result['run_id'])['approved']
    # Capturing a command that removes Git metadata retains an honest null post-state.
    p['source_paths'].remove('ignored.py')
    result = record(p, [sys.executable, '-c', 'import shutil; shutil.rmtree(".git")'])
    value = load(Path(result['receipt']))
    assert value['code']['after'] is None
    assert value['capture']['state'] == 'incomplete'
    assert verify(result['receipt'])['integrity'] == 'verified'


def test_required_skip_is_failure_even_with_exit_zero(setup):
    _, p, _ = setup
    counts = {'discovered': 8, 'executed': 7, 'passed': 7, 'failed': 0, 'skipped': 1}
    report = {'schema_version': 'counts/v1', 'counts': counts, 'test_ids': [f'fixture-{i}' for i in range(8)]}
    command = 'import pathlib,sys; pathlib.Path(sys.argv[1], "results.json").write_text(' + repr(json.dumps(report)) + ')'
    result = record(p, [sys.executable, '-c', command, '{output}'])
    assert result['child_exit_code'] == 0
    assert result['acceptance']['status'] == 'fail'


def test_tampered_target_state_and_archive_expiry_rejected(setup):
    _, p, target = setup
    result = run_fixture(p)
    import_receipt(result['receipt'], target)
    path = target.root / 'imports.json'
    original = path.read_bytes()
    value = load(path)
    value['payload']['imports'].clear()
    path.write_bytes(canonical(value))
    with pytest.raises(EvidenceError, match='integrity mismatch'):
        evaluate(target, result['run_id'])
    path.write_bytes(original)
    source = target.root / 'receipts' / result['receipt_sha256'] / 'test-results.json'
    source.unlink()
    with pytest.raises(EvidenceError, match='Missing regular file'):
        evaluate(target, result['run_id'])


def test_staged_state_is_not_lost_when_worktree_matches_head(setup):
    from cognitive_harness.evidence.capture import observe
    repo, p, _ = setup
    original = (repo / 'runner.py').read_bytes()
    def stage(value):
        (repo / 'runner.py').write_bytes(value)
        subprocess.check_call(['git', '-C', str(repo), 'add', 'runner.py'])
        (repo / 'runner.py').write_bytes(original)
        return observe(repo, p['source_paths'], p['lockfiles'])
    first = stage(original + b'\n# staged one\n')
    second = stage(original + b'\n# staged two\n')
    assert not first['clean'] and not second['clean']
    assert first['status_sha256'] == second['status_sha256']
    assert first['source_manifest'] == second['source_manifest']
    assert first['diff_sha256'] != second['diff_sha256']
