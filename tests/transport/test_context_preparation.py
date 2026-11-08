"""Tests only for #19 preparation artifacts, not checkpoint/plugin conformance."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[2]
PATH = ROOT / 'examples/context_continuity/preflight.py'
spec = importlib.util.spec_from_file_location('context_preflight', PATH)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def test_preflight_does_not_invent_capability_or_measurements(monkeypatch):
    monkeypatch.setattr(preflight.shutil, 'which', lambda name: None)
    monkeypatch.setattr(preflight, 'module_origin', lambda name: None)
    value = preflight.collect()
    assert value['opencode']['status'] == 'unavailable'
    assert value['operator_observations']['parallel_slots'] is None
    assert value['hybrid_adapter']['summary_bypass_enabled'] is False
    assert value['hybrid_adapter']['capability_probe'] == 'not_run'
    assert value['benchmark']['speedup'] is None
    assert value['missing_prerequisites']


def test_version_probe_is_fixed_argv_and_discards_raw_logs(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=b'2.0.1\nsecret-unexpected-log', returncode=0)
    monkeypatch.setattr(preflight.subprocess, 'run', run)
    value = preflight.client_version('/fixture/opencode')
    assert calls == [['/fixture/opencode', '--version']]
    assert value['version'] is None
    assert 'secret-unexpected-log' not in json.dumps(value)
    monkeypatch.setattr(preflight.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'2.0.1', returncode=0))
    assert preflight.client_version('/fixture/opencode')['version'] == '2.0.1'


@pytest.mark.parametrize('value', [{'OPENAI_API_KEY': 'secret'}, {'parallel_slots': True}, {'parallel_slots': 0},
                                  {'model_id': 'https://user:secret@host/model'}, {'tool_schema_tokens': -1}])
def test_observations_reject_full_config_or_invalid_values(value):
    with pytest.raises(ValueError):
        preflight.declared_observations(value)


def test_candidate_pairs_match_and_controls_are_definitions_only():
    root = ROOT / 'examples/context_continuity'
    profiles = json.loads((root / 'profiles.json').read_text())
    for first, second in [('B', 'C'), ('D', 'E')]:
        a, b = (profiles['profiles'][key] for key in (first, second))
        for field in ('sessions', 'context_tokens', 'transition_tokens'):
            assert a[field] == b[field]
    assert profiles['candidate_request_budget']['tool_schema_tokens'] is None
    assert profiles['status'] == 'proposed-not-applied'
    controls = json.loads((root / 'controls.json').read_text())
    assert controls['status'] == 'test-definitions-only-not-executed'
    assert len({c['id'] for c in controls['controls']}) == len(controls['controls']) == 12


def test_preflight_output_never_overwrites_previous_observation(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, 'collect', lambda obs: {'missing_prerequisites': ['not probed']})
    output = tmp_path / 'report.json'
    assert preflight.main(['--output', str(output)]) == 0
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        preflight.main(['--output', str(output)])
    assert output.read_bytes() == original
