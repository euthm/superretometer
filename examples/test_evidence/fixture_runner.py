"""Eight synthetic assertions, not application tests or independent evidence.

The result protocol is intentionally simple and usable from any language.
"""
import json
import sys
from pathlib import Path

results = [(f"fixture-{i}", i + i == 2 * i) for i in range(8)]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
(output / "results.json").write_text(json.dumps({
    "schema_version": "counts/v1",
    "counts": {"discovered": 8, "executed": 8,
               "passed": sum(p for _, p in results),
               "failed": sum(not p for _, p in results), "skipped": 0},
    "test_ids": [name for name, _ in results],
}))
print("Synthetic public fixture: 8 assertions executed")
raise SystemExit(0 if all(p for _, p in results) else 1)
