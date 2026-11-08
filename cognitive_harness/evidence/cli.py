"""Explicit CLI transport for portable evidence. JSON on stdout, no shell eval."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .capture import record
from .contracts import EvidenceError, verify
from .workflow import Target, evaluate, export_bundle, import_receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog="superretometer evidence")
    commands = parser.add_subparsers(dest="operation", required=True)
    capture = commands.add_parser("record", help="Explicitly execute and capture a local argv")
    capture.add_argument("--config", required=True)
    capture.add_argument("command", nargs=argparse.REMAINDER)
    check = commands.add_parser("verify", help="Check receipt/bundle bytes without executing commands")
    check.add_argument("path")
    check.add_argument("--repo", help="Operator-mapped checkout for current source verification")
    imp = commands.add_parser("import", help="Import through proposals into a portable target")
    imp.add_argument("path")
    imp.add_argument("--target", required=True, help="Explicit target JSON configuration")
    ev = commands.add_parser("evaluate", help="Append an evaluation using the existing gate/warrant policies")
    ev.add_argument("run_id")
    ev.add_argument("--target", required=True)
    ev.add_argument("--control", default="baseline", choices=["baseline", "commit_mismatch", "missing_validator"])
    export = commands.add_parser("export", help="Export selected historical evaluations")
    export.add_argument("evaluation_ids", nargs="+")
    export.add_argument("--target", required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.operation == "record":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = record(args.config, command)
            code = {"pass": 0, "unknown": 3, "fail": 4}[result["acceptance"]["status"]]
        elif args.operation == "verify":
            result = verify(args.path, repo=args.repo)
        elif args.operation == "import":
            result = import_receipt(args.path, Target.from_config(args.target))
        elif args.operation == "evaluate":
            result = evaluate(Target.from_config(args.target), args.run_id, control=args.control)
            code = 0 if result["approved"] else 4
        else:
            result = export_bundle(Target.from_config(args.target), args.evaluation_ids, args.output)
        print(json.dumps(result, sort_keys=True))
    except (EvidenceError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, sort_keys=True))
        code = 2
    return code


if __name__ == "__main__":
    sys.exit(main())
