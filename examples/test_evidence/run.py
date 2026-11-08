"""Run the public end-to-end workflow through separate CLI processes.

Usage: python examples/test_evidence/run.py --output /path/to/new-directory
No Memory, tokens, database or private project configuration is used.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = root / 'fixture'
    repo.mkdir()
    shutil.copyfile(Path(__file__).with_name('fixture_runner.py'), repo / 'runner.py')
    (repo / 'fixture.lock').write_text('public-synthetic-fixture=1\n')
    for command in (['init', '-q'], ['config', 'user.name', 'Public fixture'],
                    ['config', 'user.email', 'fixture@example.invalid'],
                    ['remote', 'add', 'origin', 'https://example.invalid/public/test-evidence.git'],
                    ['add', '.'], ['commit', '-qm', 'Public synthetic fixture']):
        subprocess.run(['git', '-C', str(repo), *command], check=True)
    remote = 'https://example.invalid/public/test-evidence.git'
    profile = {
        'repo': str(repo), 'source_paths': ['runner.py'], 'lockfiles': ['fixture.lock'],
        'archive': {'path': str(root / 'archive'), 'locator': (root / 'archive').as_uri(),
                    'retention': 'Retain this directory until the operator explicitly removes it; no automatic expiry'},
        'claim': {'title': 'Eight public synthetic assertions pass',
                  'scope': 'Synthetic workflow fixture only; not application parity or independent audit',
                  'declared_remote': remote, 'requested_commit': None,
                  'falsifier': 'Any missing, skipped or failed assertion, or different tested revision, invalidates this scoped claim'},
        'acceptance': {'expected_executed': 8, 'required_zero_failures': True, 'no_skips': True,
                       'required_test_ids': [f'fixture-{i}' for i in range(8)]},
        'parser': {'kind': 'counts-json/v1', 'report': 'results.json'},
        'environment': {'tools': {'python': [sys.executable, '--version']}, 'services': {},
                        'exclusions': ['Synthetic fixture; no DB, network, private adapter or independent observer']},
        'timeout_seconds': 30,
    }
    profile_path = root / 'profile.json'
    profile_path.write_text(json.dumps(profile, indent=2))
    target = root / 'target.json'
    target.write_text(json.dumps({'kind': 'portable-inmemory/v1', 'id': 'public-fixture',
                                 'root': str(root / 'target'), 'repositories': {remote: str(repo)}}, indent=2))
    def cli(*argv, expected=0):
        command = [sys.executable, '-m', 'cognitive_harness.evidence.cli', *map(str, argv)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != expected:
            raise RuntimeError(f'CLI failed ({result.returncode}): {result.stdout} {result.stderr}')
        return json.loads(result.stdout)
    captured = cli('record', '--config', profile_path, '--', sys.executable, '{repo}/runner.py', '{output}')
    imported = cli('import', captured['receipt'], '--target', target)
    replayed = cli('import', captured['receipt'], '--target', target)
    assert imported['mapping'] == replayed['mapping']
    assert replayed['status'] == 'existing'
    positive = cli('evaluate', captured['run_id'], '--target', target)
    negative = cli('evaluate', captured['run_id'], '--target', target, '--control', 'commit_mismatch', expected=4)
    missing = cli('evaluate', captured['run_id'], '--target', target, '--control', 'missing_validator', expected=4)
    gates = ('provenance', 'scope', 'worktree', 'test', 'falsifiability', 'dependency', 'freshness')
    assert all(positive['gates'][g]['status'] == 'pass' for g in gates)
    assert negative['gates']['test']['status'] == 'block'
    assert missing['gates']['test']['status'] == 'unknown'
    assert all(negative['gates'][g]['status'] == positive['gates'][g]['status'] for g in gates if g != 'test')
    values = [positive, negative, missing]
    exported = cli('export', *(v['evaluation_id'] for v in values), '--target', target, '--output', root / 'bundle')
    offline = cli('verify', root / 'bundle')
    assert offline['source_current'] == 'unavailable'
    summary = {'kind': 'synthetic-reference-example', 'receipt_sha256': captured['receipt_sha256'],
               'run_id': captured['run_id'], 'positive': {g: positive['gates'][g]['status'] for g in gates},
               'positive_approved': positive['approved'], 'warrant': positive['warrant']['warrant_status'],
               'negative_sha': negative['gates']['test']['status'],
               'missing_validator': missing['gates']['test']['status'],
               'restart_ids_preserved': True, 'offline_integrity': offline['integrity'],
               'bundle': exported['bundle'], 'manifest_sha256': exported['manifest_sha256']}
    (root / 'example-results.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
