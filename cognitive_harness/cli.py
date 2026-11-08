# FILE: cognitive-harness/cli.py
"""Superretometer CLI.

Usage:
    superretometer --version
    superretometer --help
    superretometer mcp
    superretometer checkpoint create [OPTIONS]
    superretometer checkpoint list [OPTIONS]
    superretometer checkpoint restore CHECKPOINT_ID [OPTIONS]
    superretometer checkpoint inject CHECKPOINT_ID [OPTIONS]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cognitive_harness import __version__

from cognitive_harness.model.checkpoint import SourceReference
from cognitive_harness.orchestration.checkpoint_manager import (
    CheckpointManager,
    CheckpointError,
    CheckpointBudgetError,
)
from cognitive_harness.orchestration.restore_validator import (
    RestoreValidator,
    Severity,
)


def main():
    parser = argparse.ArgumentParser(prog="superretometer")
    parser.add_argument("--version", action="version", version=__version__)

    sub = parser.add_subparsers(dest="command")

    # ── MCP ────────────────────────────────────────────────────────────
    sub.add_parser("mcp", help="Start the MCP server on stdin/stdout")

    # ── Checkpoint sub-commands ────────────────────────────────────────
    cp_parser = sub.add_parser("checkpoint", help="Checkpoint management")
    cp_sub = cp_parser.add_subparsers(dest="subcommand")

    # checkpoint create
    create_p = cp_sub.add_parser("create", help="Create a new checkpoint")
    create_p.add_argument("--project-id", required=True)
    create_p.add_argument("--project-name", required=True)
    create_p.add_argument("--repo", required=True)
    create_p.add_argument("--branch", required=True)
    create_p.add_argument("--sha", required=True)
    create_p.add_argument("--goal", action="append", default=[], dest="goals")
    create_p.add_argument("--constraint", action="append", default=[], dest="constraints")
    create_p.add_argument("--decision", action="append", default=[],
                          help="Decision as JSON: {id, rationale, outcome}")
    create_p.add_argument("--task", action="append", default=[],
                          help="Task as JSON: {task_id, description, status}")
    create_p.add_argument("--source", action="append", default=[],
                          help="Source ref as JSON: {path, sha, description}")
    create_p.add_argument("--last-message", default="",
                          help="Last user message before checkpoint")
    create_p.add_argument("--tool-action", action="append", default=[],
                          help="Active tool action as JSON: {tool, status, artifact}")
    create_p.add_argument("--budget", type=int, default=16_000)
    create_p.add_argument("--session-id", default="")
    create_p.add_argument("--output-dir", default="",
                          help="Checkpoint directory (default: ~/.superretometer/checkpoints)")

    # checkpoint list
    list_p = cp_sub.add_parser("list", help="List checkpoints")
    list_p.add_argument("--output-dir", default="",
                        help="Checkpoint directory")

    # checkpoint restore
    restore_p = cp_sub.add_parser("restore", help="Validate and render checkpoint")
    restore_p.add_argument("checkpoint_id")
    restore_p.add_argument("--project-id", default="")
    restore_p.add_argument("--budget", type=int, default=16_000)
    restore_p.add_argument("--repo-path", default="",
                           help="Git repo path for SHA verification")
    restore_p.add_argument("--output-dir", default="",
                           help="Checkpoint directory")

    # checkpoint inject (alias for restore, outputs preamble)
    inject_p = cp_sub.add_parser("inject", help="Inject checkpoint context (preamble)")
    inject_p.add_argument("checkpoint_id")
    inject_p.add_argument("--project-id", default="")
    inject_p.add_argument("--budget", type=int, default=16_000)
    inject_p.add_argument("--repo-path", default="")
    inject_p.add_argument("--output-dir", default="")

    args = parser.parse_args()

    if args.command == "mcp":
        from cognitive_harness.mcp.server import MCPServer
        server = MCPServer()
        server.run()
        return

    if args.command == "checkpoint":
        if not args.subcommand:
            cp_parser.print_help()
            sys.exit(1)
        _handle_checkpoint(args)
        return

    # No command — show help
    parser.print_help()
    sys.exit(0)


def _handle_checkpoint(args):
    mgr = CheckpointManager(
        checkpoint_dir=Path(args.output_dir) if args.output_dir else None
    )

    if args.subcommand == "create":
        _do_create(mgr, args)
    elif args.subcommand == "list":
        _do_list(mgr)
    elif args.subcommand in ("restore", "inject"):
        _do_restore(mgr, args)


def _do_create(mgr: CheckpointManager, args) -> None:
    decisions = {}
    for d in args.decision:
        try:
            parsed = json.loads(d)
            decisions[parsed.get("id", "unnamed")] = parsed
        except json.JSONDecodeError:
            print(f"# Warning: skipping invalid decision JSON: {d}", file=sys.stderr)

    tasks = []
    for t in args.task:
        try:
            tasks.append(json.loads(t))
        except json.JSONDecodeError:
            print(f"# Warning: skipping invalid task JSON: {t}", file=sys.stderr)

    sources = []
    for s in args.source:
        try:
            parsed = json.loads(s)
            sources.append(SourceReference(
                path=parsed["path"],
                sha=parsed.get("sha"),
                description=parsed.get("description", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            print(f"# Warning: skipping invalid source JSON: {s}", file=sys.stderr)

    tool_actions = []
    for ta in args.tool_action:
        try:
            tool_actions.append(json.loads(ta))
        except json.JSONDecodeError:
            print(f"# Warning: skipping invalid tool-action JSON: {ta}", file=sys.stderr)

    try:
        cp = mgr.create_checkpoint(
            project_id=args.project_id,
            project_name=args.project_name,
            repo=args.repo,
            branch=args.branch,
            sha=args.sha,
            goals=args.goals,
            constraints=args.constraints,
            decisions=decisions,
            last_user_message=args.last_message,
            open_tasks=tasks,
            active_tool_actions=tool_actions,
            source_references=sources,
            context_budget_tokens=args.budget,
            session_id=args.session_id,
        )
        print(json.dumps({
            "checkpoint_id": cp.checkpoint_id,
            "content_hash": cp.content_hash,
            "timestamp": cp.timestamp,
            "project_id": cp.project_id,
            "sha": cp.sha[:12],
        }, indent=2))
    except CheckpointError as e:
        print(f"# ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _do_list(mgr: CheckpointManager) -> None:
    checkpoints = mgr.list_checkpoints()
    print(json.dumps(checkpoints, indent=2))


def _do_restore(mgr: CheckpointManager, args) -> None:
    checkpoint_id = args.checkpoint_id
    budget = args.budget
    project_id = args.project_id
    repo_path = args.repo_path

    # Load and verify integrity
    try:
        cp = mgr.load(checkpoint_id)
    except Exception as e:
        print(f"# ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate
    validator = RestoreValidator(
        expected_project_id=project_id,
        budget_tokens=budget,
        git_repo_path=repo_path,
    )
    report = validator.validate(cp)

    # Print validation report
    print(json.dumps({
        "checkpoint_id": cp.checkpoint_id,
        "content_hash": cp.content_hash[:16],
        "safe_to_restore": report.is_safe_to_restore,
        "has_failures": report.has_failures,
        "has_warnings": report.has_warnings,
        "results": [r.to_dict() for r in report.results],
    }, indent=2))

    if report.has_failures:
        print("\n# RESTORE BLOCKED: validation failures", file=sys.stderr)
        sys.exit(2)

    # Generate context
    try:
        context = mgr.generate_restore_context(cp, budget_tokens=budget)
    except CheckpointBudgetError as e:
        print(f"\n# BUDGET BLOCKED: {e}", file=sys.stderr)
        sys.exit(3)

    if args.subcommand == "inject":
        # Output preamble
        preamble = (
            f"# CONTEXT RESTORED FROM CHECKPOINT\n"
            f"Checkpoint ID: {cp.checkpoint_id}\n"
            f"Content Hash: {cp.content_hash[:16]}\n"
            f"---\n\n"
            f"{context}"
        )
        print()
        print(preamble)
    else:
        # Output rendered context
        print("\n--- RENDERED CONTEXT ---\n")
        print(context)


if __name__ == "__main__":
    main()
