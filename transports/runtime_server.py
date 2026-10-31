#!/usr/bin/env python3
# FILE: superretometer-runtime/runtime_server.py
"""Superretometer runtime server — MCP transport over stdin/stdout.

Connects:
  OpenCode -> Superretometer MCP -> canonical cognitive_harness v0.6.3
           -> MemoryAdapter -> persistent Memory graph

All epistemisk logikk i canonical package.
stdout = MCP protocol messages only.
logger/debug = stderr.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid

# Canonical imports — never from local copies
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.analysis.simulation_gate_policy import SimulationGatePolicy
from cognitive_harness.analysis.implementation_gate_policy import ImplementationGatePolicy
from cognitive_harness.consumer.api import ConsumerAPI
from cognitive_harness.orchestration.engine import OrchestrationEngine
from cognitive_harness.model.ko import GateStatus
from cognitive_harness.model.proposal import Proposal, ProposalType
from cognitive_harness.exceptions import IncompleteEnumerationError
from cognitive_harness.mcp.protocol import tool_result

# Local adapter
sys.path.insert(0, os.path.dirname(__file__))
from memory_adapter import MemoryAdapter

# ── Logging: stderr only ─────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("superretometer.runtime")


# ── Env validation ───────────────────────────────────────────────────────

def _load_dotenv() -> dict:
    """Load .env file from runtime directory as fallback."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env = {}
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip()
    return env


def validate_env() -> dict:
    """Get required env vars, falling back to .env file."""
    dot_env = _load_dotenv()

    def get_env(name: str) -> str:
        return os.environ.get(name) or dot_env.get(name, "")

    required = ["CH_SESSION_ID", "CH_WORKSPACE", "CH_PROJECT_ID"]
    missing = [v for v in required if not get_env(v)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"Set by oc launcher or .env file before starting runtime."
        )

    mode = get_env("CH_MODE") or "standard"

    return {
        "session_id": get_env("CH_SESSION_ID"),
        "workspace": get_env("CH_WORKSPACE"),
        "project_id": get_env("CH_PROJECT_ID"),
        "mode": mode,
    }


# ── Protocol validation ──────────────────────────────────────────────────

def validate_tool_schemas() -> None:
    """Validate that every tool in TOOLS_METADATA has a valid MCP inputSchema."""
    for name, info in TOOLS_METADATA.items():
        schema = info.get("inputSchema")
        if not isinstance(schema, dict):
            raise RuntimeError(
                f"Tool '{name}' missing inputSchema — MCP 2024-11-05 requires it."
            )
        if schema.get("type") != "object":
            raise RuntimeError(
                f"Tool '{name}' inputSchema.type must be 'object', got '{schema.get('type')}'."
            )

# ── Startup ──────────────────────────────────────────────────────────────

def startup() -> dict:
    """Initialize runtime components."""
    validate_tool_schemas()
    env = validate_env()

    # Pin canonical version — fail closed if wrong version loaded
    from importlib.metadata import version as pkg_version
    canonical_version = pkg_version("cognitive-harness")
    if canonical_version not in ("0.6.4", "0.7.0"):
        raise RuntimeError(
            f"Refusing to start: cognitive-harness {canonical_version} loaded, "
            f"expected 0.6.4 or 0.7.0. Check PYTHONPATH / installed packages for stale versions."
        )

    # Log to stderr — never stdout
    log.error(  # stderr via logging
        "Superretometer runtime\n"
        "canonical_version=%s\n"
        "workspace=%s\n"
        "project_id=%s\n"
        "session_id=%s\n"
        "mode=%s",
        canonical_version,
        env["workspace"],
        env["project_id"],
        env["session_id"],
        env["mode"],
    )

    # Storage backend
    storage = MemoryAdapter(
        server_url=_load_dotenv().get("MEMORY_SERVER_URL") or os.environ.get("MEMORY_SERVER_URL"),
        api_key=_load_dotenv().get("MEMORY_API_KEY") or os.environ.get("MEMORY_API_KEY"),
        project_id=env["project_id"],
    )

    # Canonical analysis components
    warrant_analyzer = WarrantAnalyzer(storage)
    simulation_policy = SimulationGatePolicy(storage)
    implementation_policy = ImplementationGatePolicy(storage)

    # Orchestrator (needed for ConsumerAPI)
    # Note: OrchestrationEngine requires a ReasonerInterface.
    # For minimal runtime, we use a stub reasoner.
    from cognitive_harness.reasoning.interface import ReasonerInterface
    stub_reasoner = StubReasoner()
    orchestrator = OrchestrationEngine(storage, stub_reasoner)

    # Consumer API
    consumer_api = ConsumerAPI(storage, orchestrator)

    components = {
        "storage": storage,
        "warrant_analyzer": warrant_analyzer,
        "simulation_policy": simulation_policy,
        "implementation_policy": implementation_policy,
        "orchestrator": orchestrator,
        "consumer_api": consumer_api,
        "env": env,
        "canonical_version": canonical_version,
    }

    # Verify storage connectivity
    try:
        all_kos = storage.list_all_kos()
        log.error("Storage connected: %d KOs enumerated", len(all_kos))
    except Exception as e:
        log.error("Storage enumeration warning: %s", e)

    return components


class StubReasoner:
    """Minimal reasoner stub for runtime that doesn't need autonomous reasoning.
    Implements ReasonerInterface without importing it at class-definition time."""

    def start_thread(self, thread, tension_ko_ids: list[str], canonical_ids: list[str]) -> None:
        pass

    def continue_thread(self, thread) -> object:
        from cognitive_harness.model.thread import Conclusion, ConclusionType
        return Conclusion(
            type=ConclusionType.DEFERRAL,
            rationale="Stub reasoner: no autonomous reasoning in minimal runtime.",
        )


# ── MCP Protocol ─────────────────────────────────────────────────────────

class RuntimeServer:
    """JSON-RPC 2.0 server over stdin/stdout (MCP-compatible)."""

    def __init__(self, components: dict):
        self.components = components
        self.request_id = 0

    def run(self):
        """Read JSON-RPC requests from stdin, write responses to stdout."""
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                self._send_error(-32700, f"Parse error: {e}")
                continue

            method = msg.get("method", "")
            params = msg.get("params", {})
            req_id = msg.get("id")

            # Notifications have no id — no response
            if req_id is None:
                log.debug("Notification %s, no response", method)
                continue

            if method == "initialize":
                self._send_response(
                    id=req_id,
                    result={
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "superretometer",
                            "version": self.components["canonical_version"],
                        },
                        "capabilities": {
                            "tools": {
                                "listChanged": False,
                            }
                        },
                    },
                )
                continue

            if method == "notifications/initialized":
                log.info("Client initialized")
                continue

            if method == "shutdown":
                self._send_response(id=req_id, result={})
                return

            if method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                result = self._handle_tool(tool_name, tool_args)
                self._send_response(
                    id=req_id,
                    result=tool_result(
                        result, is_error=isinstance(result, dict) and "error" in result
                    ),
                )
            elif method == "tools/list":
                tools = self._list_tools()
                self._send_response(id=req_id, result={"tools": tools})
            else:
                self._send_error(req_id, f"Unknown method: {method}")

    def _handle_tool(self, name: str, args: dict) -> dict:
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler(self.components, args)
        except Exception as e:
            return {"error": f"{name}: {e}"}

    def _list_tools(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"],
            }
            for name, info in TOOLS_METADATA.items()
        ]

    def _send_response(self, id: int, result: dict | None = None):
        resp = {"jsonrpc": "2.0", "id": id, "result": result or {}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

    def _send_error(self, id: int, message: str):
        resp = {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": message},
            "id": id,
        }
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


# ── Tool handlers ────────────────────────────────────────────────────────

def handle_orientation(components: dict, args: dict) -> dict:
    return {
        "identity": "Superretometer",
        "canonical_version": components["canonical_version"],
        "workspace": components["env"]["workspace"],
        "project_id": components["env"]["project_id"],
        "session_id": components["env"]["session_id"],
        "mode": components["env"]["mode"],
        "storage_backend": "MemoryAdapter",
        "persistent_graph": True,
    }


def handle_get_ko(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    ko = components["storage"].get_ko(ko_id)
    if ko is None:
        return {"error": f"KO {ko_id} not found"}
    api = components["consumer_api"]
    return api._present_ko(ko, summary=False)


def handle_search_knowledge(components: dict, args: dict) -> dict:
    query = args.get("query", "")
    limit = args.get("limit", 10)
    viewpoint = args.get("viewpoint")
    api = components["consumer_api"]
    results = api.query(query, viewpoint, limit)
    return {"results": results, "count": len(results)}


def handle_check_warrant(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    orchestrator = components["orchestrator"]
    return orchestrator.check_warrant(ko_id)


def handle_justification_path(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    api = components["consumer_api"]
    path = api.justification_path(ko_id)
    return {"path": path}


def handle_scan_anti_patterns(components: dict, args: dict) -> dict:
    orchestrator = components["orchestrator"]
    try:
        findings = orchestrator.scan_anti_patterns()
        return {"findings": findings, "count": len(findings)}
    except IncompleteEnumerationError as e:
        return {"error": "IncompleteEnumerationError", "message": str(e)}


def handle_impact_set(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    api = components["consumer_api"]
    impacted = api.impact_set(ko_id)
    return {"impacted": impacted, "count": len(impacted)}


def handle_review_required(components: dict, args: dict) -> dict:
    api = components["consumer_api"]
    if not api.storage.enumeration_complete:
        return {
            "error": "IncompleteEnumerationError",
            "message": "list_review_required requires complete enumeration. "
                       "This storage backend cannot guarantee list_all_kos() returns every KO."
        }
    items = api.list_review_required()
    return {"items": items, "count": len(items)}


def handle_check_simulation_gates(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    policy = components["simulation_policy"]
    report = policy.evaluate_gates(ko_id)
    result = report.to_dict()
    result["all_pass"] = report.all_pass()
    result["any_block"] = report.any_block()
    result["any_unknown"] = report.any_unknown()
    return result


def handle_check_implementation_gates(components: dict, args: dict) -> dict:
    ko_id = args.get("ko_id", "")
    policy = components["implementation_policy"]
    return policy.evaluate_gates(ko_id)


def handle_adopt_existing_ko(components: dict, args: dict) -> dict:
    """Adopt an existing Memory object as a CH KnowledgeObject."""
    storage = components["storage"]
    existing_uuid = args.get("existing_mem_uuid", "")
    if not existing_uuid:
        return {"error": "existing_mem_uuid is required"}

    ch_id = args.get("ch_id")
    title = args.get("title", "")
    ko_type = args.get("ko_type")
    truth_category = args.get("truth_category")
    epistemic_status = args.get("epistemic_status")
    confidence = args.get("confidence")
    scope = args.get("scope", "")
    source = args.get("source", "adopted")

    adopted_id = storage.adopt_existing_ko(
        existing_mem_uuid=existing_uuid,
        ch_id=ch_id,
        title=title,
        ko_type=ko_type,
        truth_category=truth_category,
        epistemic_status=epistemic_status,
        confidence=confidence,
        scope=scope,
        source=source,
    )

    # Verify it's now accessible
    ko = storage.get_ko(adopted_id)
    return {
        "adopted_ch_id": adopted_id,
        "title": ko.title if ko else adopted_id,
        "message": f"Adopted {existing_uuid} as CH KO {adopted_id}",
    }


def handle_submit_proposal(components: dict, args: dict) -> dict:
    """Submit a structured proposal."""
    from cognitive_harness.model.proposal import Proposal, ProposalType
    from cognitive_harness.model.ko import KOType, EpistemicStatus

    storage = components["storage"]

    p_type_str = args.get("proposal_type", "create_ko")
    try:
        p_type = ProposalType(p_type_str)
    except ValueError:
        return {"error": f"Unknown proposal type: {p_type_str}"}

    proposal = Proposal(
        type=p_type,
        proposer=args.get("proposer", ""),
        rationale=args.get("rationale", ""),
    )

    if p_type == ProposalType.CREATE_KO:
        proposal.ko_title = args.get("ko_title", "")
        ktype = args.get("ko_type")
        if ktype:
            try:
                proposal.ko_type = KOType(ktype)
            except ValueError:
                pass
        content = args.get("ko_content")
        if content:
            try:
                proposal.ko_content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                proposal.ko_content = content

    elif p_type in (ProposalType.UPDATE_KO, ProposalType.TRANSITION_STATUS):
        proposal.target_ko_id = args.get("target_ko_id", "")
        if p_type == ProposalType.TRANSITION_STATUS:
            ts = args.get("target_status")
            if ts:
                try:
                    proposal.target_status = EpistemicStatus(ts)
                except ValueError:
                    pass
        elif p_type == ProposalType.UPDATE_KO:
            updates = args.get("updates", "{}")
            try:
                proposal.updates = json.loads(updates)
            except (json.JSONDecodeError, TypeError):
                proposal.updates = {}

    elif p_type == ProposalType.CREATE_EVIDENCE:
        proposal.evidence_claim_id = args.get("evidence_claim_id", "")
        proposal.evidence_observation = args.get("evidence_observation", "")

    proposal_id = storage.submit_proposal(proposal)
    return {"proposal_id": proposal_id, "state": proposal.state.value}


def handle_execute_proposal(components: dict, args: dict) -> dict:
    """Validate and execute a proposal."""
    proposal_id = args.get("proposal_id", "")
    if not proposal_id:
        return {"error": "proposal_id is required"}

    storage = components["storage"]
    try:
        result = storage.validate_and_execute(proposal_id)
        return {
            "proposal_id": result.id,
            "state": result.state.value if hasattr(result.state, 'value') else str(result.state),
            "rejection_reason": result.rejection_reason,
            "created_ko_id": result.created_ko_id,
            "created_evidence_id": result.created_evidence_id,
        }
    except ValueError as e:
        return {"error": str(e)}


# ── Tool registry ────────────────────────────────────────────────────────

TOOLS_METADATA = {
    "orientation": {
        "description": "Get runtime identity, version, and storage status",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_ko": {
        "description": "Read a KnowledgeObject by ID",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "search_knowledge": {
        "description": "Search knowledge graph semantically",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "viewpoint": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "check_warrant": {
        "description": "Compute epistemic warrant for a conclusion KO",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "justification_path": {
        "description": "Get the justification path for a KO",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "scan_anti_patterns": {
        "description": "Scan all KOs for epistemic anti-patterns",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "impact_set": {
        "description": "Compute downstream impact set for a KO",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "review_required": {
        "description": "List KOs marked for review",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "check_simulation_gates": {
        "description": "Evaluate simulation gates for a claim KO",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "check_implementation_gates": {
        "description": "Evaluate implementation gates (provenance, scope, test) for a code-bearing claim KO",
        "inputSchema": {
            "type": "object",
            "properties": {"ko_id": {"type": "string"}},
            "required": ["ko_id"],
        },
    },
    "adopt_existing_ko": {
        "description": "Adopt an existing Memory object as a CH KnowledgeObject. Creates a CH wrapper with proper ch_* properties that links to the original.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "existing_mem_uuid": {"type": "string", "description": "UUID of the existing Memory object to adopt"},
                "ch_id": {"type": "string", "description": "Canonical CH ID (auto-derived from existing key if omitted)"},
                "title": {"type": "string", "description": "KO title"},
                "ko_type": {"type": "string", "description": "KOType: requirement, observation, finding, hypothesis, conclusion, etc."},
                "truth_category": {"type": "string", "description": "TruthCategory: assumption, physical_observation, etc."},
                "epistemic_status": {"type": "string", "description": "EpistemicStatus: proposed, validated, canonical, etc."},
                "confidence": {"type": "string", "description": "ConfidenceLevel: speculative, low, medium, high, certain"},
                "scope": {"type": "string", "description": "Scope/domain string"},
                "source": {"type": "string", "description": "Provenance source (default: adopted)"},
            },
            "required": ["existing_mem_uuid"],
        },
    },
    "submit_proposal": {
        "description": "Submit a structured proposal for state change. Persists to Memory for durability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_type": {"type": "string", "description": "ProposalType: create_ko, update_ko, transition_status, create_relation, create_evidence"},
                "proposer": {"type": "string", "description": "Agent/human identifier"},
                "rationale": {"type": "string", "description": "Why this change is needed"},
                "ko_title": {"type": "string", "description": "KO title (for create_ko)"},
                "ko_type": {"type": "string", "description": "KOType (for create_ko)"},
                "ko_content": {"type": "string", "description": "KO content as JSON string (for create_ko)"},
                "target_ko_id": {"type": "string", "description": "Target KO ID (for update/transition)"},
                "target_status": {"type": "string", "description": "Target EpistemicStatus (for transition)"},
                "updates": {"type": "string", "description": "Updates as JSON string (for update_ko)"},
                "evidence_claim_id": {"type": "string", "description": "Claim ID (for create_evidence)"},
                "evidence_observation": {"type": "string", "description": "Observation (for create_evidence)"},
            },
            "required": ["proposal_type", "proposer", "rationale"],
        },
    },
    "execute_proposal": {
        "description": "Validate and execute a submitted proposal. Applies the requested mutation deterministically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string", "description": "Proposal ID to execute"},
            },
            "required": ["proposal_id"],
        },
    },
}

TOOL_HANDLERS = {
    "orientation": handle_orientation,
    "get_ko": handle_get_ko,
    "search_knowledge": handle_search_knowledge,
    "check_warrant": handle_check_warrant,
    "justification_path": handle_justification_path,
    "scan_anti_patterns": handle_scan_anti_patterns,
    "impact_set": handle_impact_set,
    "review_required": handle_review_required,
    "check_simulation_gates": handle_check_simulation_gates,
    "check_implementation_gates": handle_check_implementation_gates,
    "adopt_existing_ko": handle_adopt_existing_ko,
    "submit_proposal": handle_submit_proposal,
    "execute_proposal": handle_execute_proposal,
}


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    components = startup()
    server = RuntimeServer(components)
    server.run()


if __name__ == "__main__":
    main()
