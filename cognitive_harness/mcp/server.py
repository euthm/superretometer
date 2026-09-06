# FILE: cognitive-harness/mcp/server.py
"""Superretometer MCP Server (Cognitive Harness) — JSON-RPC over stdio.

Standalone MCP server using InMemoryStorage. For production use with
a persistent knowledge graph, replace InMemoryStorage with a storage
implementation that conforms to StorageInterface.

Usage:
    superretometer mcp

Or as a module:
    python -m cognitive_harness.mcp.server
"""
from __future__ import annotations
import json
import sys
import uuid
from datetime import datetime, timezone

from cognitive_harness import __version__

from cognitive_harness.model.ko import (
    KnowledgeObject, KOType, EpistemicStatus, ConfidenceLevel,
    RelationType, Provenance, Dataset, TruthCategory, WarrantStatus,
)
from cognitive_harness.model.proposal import Proposal, ProposalType, ProposalState
from cognitive_harness.model.tension import Tension, TensionPriority, TensionStatus
from cognitive_harness.storage.inmemory import InMemoryStorage
from cognitive_harness.reasoning.rule_engine import RuleEngineReasoner
from cognitive_harness.orchestration.engine import OrchestrationEngine
from cognitive_harness.analysis.warrant_analyzer import WarrantAnalyzer
from cognitive_harness.consumer.api import ConsumerAPI


# ── Tool definitions ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "orientation",
        "description": "Return current state of the knowledge graph",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "description": "Optional scope filter"},
            },
        },
    },
    {
        "name": "check_warrant",
        "description": "Compute warrant status for a conclusion",
        "inputSchema": {
            "type": "object",
            "required": ["conclusion_ko_id"],
            "properties": {
                "conclusion_ko_id": {"type": "string"},
            },
        },
    },
    {
        "name": "justification_path",
        "description": "Get the justification path for a Knowledge Object",
        "inputSchema": {
            "type": "object",
            "required": ["ko_id"],
            "properties": {
                "ko_id": {"type": "string"},
            },
        },
    },
    {
        "name": "scan_anti_patterns",
        "description": "Scan all KOs for structural anti-patterns",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_tensions",
        "description": "List open tensions in the system",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "review_required",
        "description": "List KOs marked as review-required",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "impact_set",
        "description": "Find KOs affected by a change",
        "inputSchema": {
            "type": "object",
            "required": ["ko_id"],
            "properties": {
                "ko_id": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_ko",
        "description": "Propose a new Knowledge Object",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "proposer": {"type": "string"},
                "ko_type": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "scope": {"type": "string"},
                "rationale": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_relation",
        "description": "Propose a new relation between Knowledge Objects",
        "inputSchema": {
            "type": "object",
            "required": ["from_ko_id", "to_ko_id", "relation_type"],
            "properties": {
                "from_ko_id": {"type": "string"},
                "to_ko_id": {"type": "string"},
                "relation_type": {"type": "string"},
                "proposer": {"type": "string"},
                "rationale": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_evidence",
        "description": "Propose evidence for a claim",
        "inputSchema": {
            "type": "object",
            "required": ["claim_ko_id"],
            "properties": {
                "claim_ko_id": {"type": "string"},
                "observation": {"type": "string"},
                "records": {"type": "array", "items": {"type": "string"}},
                "proposer": {"type": "string"},
                "rationale": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_tension",
        "description": "Propose a new tension",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "ko_ids": {"type": "array", "items": {"type": "string"}},
                "proposer": {"type": "string"},
                "rationale": {"type": "string"},
            },
        },
    },
]


class MCPServer:
    """MCP stdio server for Superretometer (Cognitive Harness reference implementation)."""

    def __init__(self):
        self.storage = InMemoryStorage()
        self.reasoner = RuleEngineReasoner(self.storage)
        self.engine = OrchestrationEngine(self.storage, self.reasoner)
        self.wa = WarrantAnalyzer(self.storage)
        self.api = ConsumerAPI(self.storage, self.engine)
        self._json_id = 0

    def _next_id(self):
        self._json_id += 1
        return self._json_id

    def _respond(self, response):
        msg = {"jsonrpc": "2.0", "id": response.get("id"), "result": response.get("result")}
        if "error" in response:
            msg["error"] = response["error"]
            if "result" in msg:
                del msg["result"]
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def _handle_tools_list(self, request):
        self._respond({"id": request.get("id"), "result": {"tools": TOOLS}})

    def _handle_call(self, request):
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        rid = request.get("id")

        handlers = {
            "orientation": self._handle_orientation,
            "check_warrant": self._handle_check_warrant,
            "justification_path": self._handle_justification_path,
            "scan_anti_patterns": self._handle_scan_anti_patterns,
            "open_tensions": self._handle_open_tensions,
            "review_required": self._handle_review_required,
            "impact_set": self._handle_impact_set,
            "propose_ko": self._handle_propose_ko,
            "propose_relation": self._handle_propose_relation,
            "propose_evidence": self._handle_propose_evidence,
            "propose_tension": self._handle_propose_tension,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            self._respond({"id": rid, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})
            return

        try:
            result = handler(arguments)
            self._respond({"id": rid, "result": result})
        except Exception as e:
            self._respond({"id": rid, "error": {"code": -32603, "message": str(e)}})

    # ── Tool handlers ────────────────────────────────────────────────

    def _handle_orientation(self, args):
        scope = args.get("scope")
        kos = self.storage.list_all_kos()
        conclusions = [k for k in kos if k.type == KOType.CONCLUSION]
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_kos": len(kos),
            "conclusions": len(conclusions),
            "canonical": len(self.storage.list_canonical(scope)),
            "review_required": len(self.storage.list_review_required()),
        }

    def _handle_check_warrant(self, args):
        ko_id = args["conclusion_ko_id"]
        result = self.wa.compute_warrant(ko_id)
        return {
            "conclusion_ko_id": ko_id,
            "warrant_status": result.warrant_status.value,
            "supporting_kos": result.supporting_kos,
            "independent_kos": result.independent_kos,
            "dependent_kos": result.dependent_kos,
            "anti_pattern_diagnoses": [
                {
                    "pattern": d.pattern.value,
                    "offending_ko_ids": d.offending_ko_ids,
                    "justification_path": d.justification_path,
                    "provenance_roots": d.provenance_roots,
                    "violated_condition": d.violated_condition,
                    "suggested_missing_evidence": d.suggested_missing_evidence,
                }
                for d in result.anti_pattern_diagnoses
            ],
        }

    def _handle_justification_path(self, args):
        path_ids = self.storage.get_justification_path(args["ko_id"])
        return [
            {
                "id": kid,
                "title": (self.storage.get_ko(kid) or KnowledgeObject()).title,
            }
            for kid in path_ids
        ]

    def _handle_scan_anti_patterns(self, args):
        findings = self.wa.detect_all_anti_patterns()
        return [
            {
                "pattern": f.pattern.value,
                "offending_ko_ids": f.offending_ko_ids,
                "justification_path": f.justification_path,
                "provenance_roots": f.provenance_roots,
                "violated_condition": f.violated_condition,
                "suggested_missing_evidence": f.suggested_missing_evidence,
            }
            for f in findings
        ]

    def _handle_open_tensions(self, args):
        """List open tensions. Note: no public API for tension listing yet."""
        open_tensions = [
            t for t in self.engine._tensions.values()
            if not t.status.is_terminal
        ]
        return [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "priority": t.priority.value,
                "status": t.status.value,
                "ko_ids": t.ko_ids,
                "thread_ids": [th.id for th in t.threads],
            }
            for t in open_tensions
        ]

    def _handle_review_required(self, args):
        return self.api.list_review_required()

    def _handle_impact_set(self, args):
        impacted = self.storage.compute_impact_set(args["ko_id"])
        return [
            {
                "id": kid,
                "title": (self.storage.get_ko(kid) or KnowledgeObject()).title,
            }
            for kid in impacted
        ]

    def _handle_propose_ko(self, args):
        pid = self.api.propose_ko(
            proposer=args.get("proposer", ""),
            ko_type=KOType(args["ko_type"]) if args.get("ko_type") else None,
            title=args["title"],
            content=args.get("content"),
            viewpoints=args.get("viewpoints", []),
            scope=args.get("scope", ""),
            rationale=args.get("rationale", ""),
        )
        return {"proposal_id": pid}

    def _handle_propose_relation(self, args):
        pid = self.api.propose_relation(
            proposer=args.get("proposer", ""),
            from_ko_id=args["from_ko_id"],
            to_ko_id=args["to_ko_id"],
            relation_type=RelationType(args["relation_type"]),
            rationale=args.get("rationale", ""),
        )
        return {"proposal_id": pid}

    def _handle_propose_evidence(self, args):
        pid = self.api.propose_evidence(
            proposer=args.get("proposer", ""),
            claim_id=args["claim_ko_id"],
            observation=args.get("observation", ""),
            records=args.get("records", []),
            rationale=args.get("rationale", ""),
        )
        return {"proposal_id": pid}

    def _handle_propose_tension(self, args):
        pid = self.api.propose_tension(
            proposer=args.get("proposer", ""),
            title=args["title"],
            description=args.get("description", ""),
            ko_ids=args.get("ko_ids", []),
            viewpoints=args.get("viewpoints", []),
            rationale=args.get("rationale", ""),
        )
        return {"proposal_id": pid}

    # ── Main loop ────────────────────────────────────────────────────

    def run(self):
        # Handle initialize
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = request.get("method", "")

            if method == "initialize":
                self._respond({
                    "id": request.get("id"),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "superretometer", "version": __version__},
                        "capabilities": {
                            "tools": {"listChanged": False},
                        },
                    },
                })
            elif method == "tools/list":
                self._handle_tools_list(request)
            elif method == "tools/call":
                self._handle_call(request)


def main():
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
