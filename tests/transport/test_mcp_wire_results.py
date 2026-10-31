"""Exercise serialized MCP replies, not just the underlying Python handlers.

The legacy runtime uses an isolated in-memory storage fixture here. Memory,
Cloudflare, model providers and AI1 persistence are deliberately not exercised.
"""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy
from cognitive_harness.consumer.api import ConsumerAPI
from cognitive_harness.mcp.server import MCPServer
from cognitive_harness.orchestration.engine import OrchestrationEngine
from cognitive_harness.reasoning.rule_engine import RuleEngineReasoner
from cognitive_harness.storage.inmemory import InMemoryStorage


def decode_tool_reply(message, *, error=False):
    assert message['jsonrpc'] == '2.0'
    assert 'error' not in message
    result = message['result']
    assert isinstance(result.get('content'), list), result
    assert len(result['content']) == 1
    assert result['content'][0]['type'] == 'text'
    assert result['isError'] is error
    return json.loads(result['content'][0]['text'])


def request(method, **params):
    return {'jsonrpc': '2.0', 'id': 7, 'method': method, 'params': params}


def stock_call(server, capsys, name, arguments=None):
    server._handle_call(request('tools/call', name=name, arguments=arguments or {}))
    return json.loads(capsys.readouterr().out)


def test_stock_orientation_is_visible_on_wire(capsys):
    payload = decode_tool_reply(stock_call(MCPServer(), capsys, 'orientation'))
    assert payload['total_kos'] == 0


@pytest.mark.parametrize('name', ['scan_anti_patterns', 'open_tensions'])
def test_stock_empty_lists_are_not_erased(capsys, name):
    assert decode_tool_reply(stock_call(MCPServer(), capsys, name)) == []


def test_stock_submission_is_visible_but_not_execution(capsys):
    server = MCPServer()
    payload = decode_tool_reply(stock_call(server, capsys, 'propose_ko', {'title': 'fixture'}))
    proposal_id = payload['proposal_id']
    assert server.storage.list_all_kos() == []
    result = server.engine.execute_proposal(proposal_id)
    assert result.state.value == 'accepted'
    assert len(server.storage.list_all_kos()) == 1


def test_stock_unknown_tool_retains_jsonrpc_error(capsys):
    reply = stock_call(MCPServer(), capsys, 'does-not-exist')
    assert reply['error']['code'] == -32601
    assert 'result' not in reply


def test_stock_stdio_client_sees_tool_payloads_and_handshake():
    calls = [request('initialize'), request('tools/list'),
             request('tools/call', name='orientation', arguments={}),
             request('tools/call', name='propose_ko', arguments={'title': 'fixture'})]
    proc = subprocess.run([sys.executable, '-m', 'cognitive_harness.mcp.server'],
                          input=''.join(json.dumps(c) + '\n' for c in calls),
                          text=True, capture_output=True, timeout=15)
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(replies) == 4
    assert replies[0]['result']['serverInfo']['name'] == 'superretometer'
    assert 'content' not in replies[0]['result']
    assert replies[1]['result']['tools']
    assert 'content' not in replies[1]['result']
    assert decode_tool_reply(replies[2])['total_kos'] == 0
    assert decode_tool_reply(replies[3])['proposal_id']


@pytest.fixture
def runtime(monkeypatch):
    # Import the transport without requiring its optional private HTTP adapter.
    adapter = types.ModuleType('memory_adapter')
    adapter.MemoryAdapter = object
    monkeypatch.setitem(sys.modules, 'memory_adapter', adapter)
    path_before = list(sys.path)
    path = Path(__file__).resolve().parents[2] / 'transports' / 'runtime_server.py'
    spec = importlib.util.spec_from_file_location('_runtime_wire_fixture', path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = path_before
    storage = InMemoryStorage()
    engine = OrchestrationEngine(storage, RuleEngineReasoner(storage))
    components = {'storage': storage, 'consumer_api': ConsumerAPI(storage, engine),
                  'implementation_policy': ImplementationGatePolicy(storage),
                  'canonical_version': '0.7.0',
                  'env': {'workspace': 'test-fixture', 'project_id': 'test-project',
                          'session_id': 'test-session', 'mode': 'test'}}
    return module.RuntimeServer(components)


def runtime_request(runtime, monkeypatch, method, **params):
    output = io.StringIO()
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(request(method, **params)) + '\n'))
    monkeypatch.setattr(sys, 'stdout', output)
    runtime.run()
    return json.loads(output.getvalue())


def runtime_call(runtime, monkeypatch, name, arguments=None):
    return runtime_request(runtime, monkeypatch, 'tools/call',
                           name=name, arguments=arguments or {})


def test_runtime_handshake_and_tools_list_are_not_tool_results(runtime, monkeypatch):
    hello = runtime_request(runtime, monkeypatch, 'initialize')['result']
    assert hello['serverInfo']['version'] == '0.7.0'
    assert 'content' not in hello
    tools = runtime_request(runtime, monkeypatch, 'tools/list')['result']
    assert any(t['name'] == 'check_implementation_gates' for t in tools['tools'])
    assert 'content' not in tools


def test_runtime_success_is_visible(runtime, monkeypatch):
    reply = runtime_call(runtime, monkeypatch, 'orientation')
    assert decode_tool_reply(reply)['identity'] == 'Superretometer'


@pytest.mark.parametrize('name,args', [('does-not-exist', {}), ('get_ko', {'ko_id': 'missing'})])
def test_runtime_tool_errors_are_visible(runtime, monkeypatch, name, args):
    assert decode_tool_reply(runtime_call(runtime, monkeypatch, name, args), error=True)['error']


def test_runtime_write_failure_is_not_empty_success(runtime, monkeypatch):
    def broken_write(proposal):
        raise OSError('controlled unavailable storage')
    monkeypatch.setattr(runtime.components['storage'], 'submit_proposal', broken_write)
    reply = runtime_call(runtime, monkeypatch, 'submit_proposal',
                         {'proposal_type': 'create_ko', 'proposer': 'test',
                          'ko_title': 'fixture', 'rationale': 'test'})
    assert 'controlled unavailable storage' in decode_tool_reply(reply, error=True)['error']


def test_runtime_submission_execution_readback_and_actual_gates(runtime, monkeypatch):
    # A hand-written gates table must not turn into an actual policy PASS.
    payload = {'scope': 'fixture', 'gates': {'test': 'PASS'}}
    submitted = decode_tool_reply(runtime_call(runtime, monkeypatch, 'submit_proposal',
        {'proposal_type': 'create_ko', 'proposer': 'test', 'rationale': 'wire fixture',
         'ko_title': 'fixture', 'ko_content': json.dumps(payload)}))
    assert submitted['state'] == 'pending'
    assert runtime.components['storage'].list_all_kos() == []
    executed = decode_tool_reply(runtime_call(runtime, monkeypatch, 'execute_proposal',
                                {'proposal_id': submitted['proposal_id']}))
    assert executed['state'] == 'accepted'
    kid = executed['created_ko_id']
    readback = decode_tool_reply(runtime_call(runtime, monkeypatch, 'get_ko', {'ko_id': kid}))
    assert readback['title'] == 'fixture'
    gates = decode_tool_reply(runtime_call(runtime, monkeypatch, 'check_implementation_gates', {'ko_id': kid}))
    assert gates['provenance']['status'] == 'block'
    assert gates['design_bearing'] is False
