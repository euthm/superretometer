"""Read-only #19 preparation diagnostics, not a context engine or benchmark.

Only the resolved OpenCode executable's fixed --version command is invoked.
No model calls, home configuration reads, environment dumps or setting writes.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NUMERIC = {'context_tokens_per_slot', 'parallel_slots', 'system_tokens', 'tool_schema_tokens', 'output_reserve_tokens'}
TEXT = {'model_id', 'quantization', 'model_server_version', 'tokenizer_id', 'tokenizer_revision'}
OBSERVATION_KEYS = NUMERIC | TEXT


def declared_observations(value):
    """Accept only deliberate, nonsecret experiment observations; no full configs."""
    if not isinstance(value, dict) or value.keys() - OBSERVATION_KEYS:
        raise ValueError('Unknown observation keys; do not supply an OpenCode config or environment dump')
    result = {key: None for key in sorted(OBSERVATION_KEYS)}
    for key, item in value.items():
        if item is None:
            continue
        if key in NUMERIC and (type(item) is not int or item < 0):
            raise ValueError(f'{key} must be a nonnegative integer or null')
        if key in {'context_tokens_per_slot', 'parallel_slots', 'output_reserve_tokens'} and item == 0:
            raise ValueError(f'{key} must be positive when supplied')
        if key in TEXT and (not isinstance(item, str) or not item.strip() or len(item) > 256
                            or any(ord(c) < 32 for c in item) or '://' in item):
            raise ValueError(f'{key} must be a short non-URL label')
        result[key] = item
    return result


def client_version(executable):
    if executable is None:
        return {'status': 'unavailable', 'version': None, 'reason': 'opencode executable not on this interpreter process PATH'}
    try:
        result = subprocess.run([executable, '--version'], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return {'status': 'unavailable', 'version': None, 'reason': 'Version probe failed or timed out; raw output not persisted'}
    # Persist only a version-shaped value, not startup logs or credentials.
    text = result.stdout.decode('utf-8', errors='replace').strip()
    match = re.fullmatch(r'(?:opencode\s+)?v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)', text)
    if result.returncode != 0 or match is None:
        return {'status': 'unavailable', 'version': None, 'reason': 'Unrecognized version response; raw output not persisted'}
    return {'status': 'observed', 'version': match.group(1), 'reason': None}


def module_origin(name):
    try:
        spec = importlib.util.find_spec(name)
        return spec.origin if spec else None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


def collect(observations=None):
    declarations = declared_observations(observations or {})
    try:
        version = importlib.metadata.version('cognitive-harness')
    except importlib.metadata.PackageNotFoundError:
        version = None
    modules = {key: module_origin(key) for key in ('cognitive_harness', 'cognitive_harness.evidence')}
    client = client_version(shutil.which('opencode'))
    blockers = []
    if client['status'] != 'observed':
        blockers.append('Installed OpenCode version has not been observed')
    if modules['cognitive_harness.evidence'] is None:
        blockers.append('Issue #18 evidence module is unavailable in this interpreter')
    for key, value in declarations.items():
        if value is None:
            blockers.append(f'{key} is unknown')
    return {
        'schema_version': 'context-preflight/v1',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'phase': 'preparation-only',
        'measurement_origin': 'current diagnostic interpreter; not proof of the running MCP process',
        'python': {'executable': sys.executable, 'version': platform.python_version()},
        'superretometer': {'version': version, 'modules': modules,
                          'temporary_checkout': any(p and '/tmp/' in p for p in modules.values())},
        'opencode': client,
        'operator_observations': declarations,
        'observation_trust': 'operator supplied; not automatically verified against a model server',
        'hybrid_adapter': {'capability_probe': 'not_run', 'pinned_build': None, 'summary_bypass_enabled': False},
        'benchmark': {'status': 'not_run', 'speedup': None, 'token_savings': None},
        'missing_prerequisites': blockers + ['Checkpoint implementation and exact-build OpenCode hook/fallback controls are not yet verified'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observations', type=Path, help='Allowlisted observed-values JSON; never the full client config')
    args = parser.parse_args(argv)
    value = json.loads(args.observations.read_text()) if args.observations else {}
    report = collect(value)
    # No overwrite; preserve each observation event with a new output name.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps({'status': 'preflight_saved', 'report': str(args.output),
                      'benchmark': 'not_run', 'missing_prerequisites': report['missing_prerequisites']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
