"""Keep checked-in website/README package metadata in sync (Python 3.10+).

Run after changing pyproject.toml; CI uses --check without modifying files.
Only marked blocks are generated. Historical release notes remain unchanged.
Also checks that the install command agrees across README, index.html and
the current release notes.  CI fails when the three sources differ.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN generated:package-metadata -->"
END = "<!-- END generated:package-metadata -->"
INSTALL_PATTERN = re.compile(
    r"pip install [^\s<`']+superretometer[@\w.-]*", re.IGNORECASE
)


def package_version(root: Path) -> str:
    # Read the project's deliberately simple literal without requiring tomllib
    # (3.11+) or adding a dependency to a Python 3.10 documentation check.
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    versions = re.findall(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$',
                          project.group(1) if project else "", re.MULTILINE)
    if len(versions) != 1:
        raise ValueError("Expected one literal x.y.z version in [project]")
    return versions[0]


def metadata_blocks(root: Path) -> dict[str, str]:
    version = package_version(root)
    notes = f"docs/releases/v{version}.md"
    if not (root / notes).is_file():
        raise ValueError(f"Missing version notes: {notes}")
    return {
        "README.md": (
            f"The current repository package version is **{version}** "
            "(see `pyproject.toml`).\n"
            f"[Version notes]({notes}) describe their release status; "
            "[the changelog](CHANGELOG.md) tracks subsequent changes on main."
        ),
        "docs/index.html": (
            "    <p>\n"
            f"      Repository package version: <strong>{version}</strong>\n"
            '      (<a href="https://github.com/euthm/superretometer/blob/main/pyproject.toml" '
            'target="_blank" rel="noopener">pyproject.toml</a>).\n'
            f'      <a href="releases/v{version}.md">Version notes</a> describe their release status;\n'
            '      <a href="https://github.com/euthm/superretometer/blob/main/CHANGELOG.md">the changelog</a>\n'
            "      tracks subsequent changes on main. This is not a published-package or running-server version check.\n"
            "    </p>"
        ),
    }


def synchronize(root: Path, *, check: bool = False) -> list[str]:
    replacements = {}
    for name, block in metadata_blocks(root).items():
        path = root / name
        text = path.read_text(encoding="utf-8")
        if text.count(START) != 1 or text.count(END) != 1:
            raise ValueError(f"Expected one metadata block in {name}")
        before, rest = text.split(START)
        _, after = rest.split(END)
        replacements[name] = before + START + "\n" + block + "\n" + END + after
    changed = []
    for name, expected in replacements.items():
        path = root / name
        if path.read_text(encoding="utf-8") != expected:
            changed.append(name)
            if not check:
                path.write_text(expected, encoding="utf-8")
    return changed


def check_install_consistency(root: Path) -> list[str]:
    """Return list of files with inconsistent install commands."""
    version = package_version(root)
    expected = f"pip install git+https://github.com/euthm/superretometer@v{version}"
    targets = ["README.md", "docs/index.html"]
    release = f"docs/releases/v{version}.md"
    if (root / release).is_file():
        targets.append(release)
    drift = []
    for name in targets:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        matches = INSTALL_PATTERN.findall(text)
        if not matches:
            # No install command — not a drift issue
            continue
        for m in matches:
            # Normalize whitespace for comparison
            norm_m = " ".join(m.split())
            norm_exp = " ".join(expected.split())
            if norm_m != norm_exp:
                drift.append(f"{name}: found '{m}', expected '{expected}'")
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on drift; do not write")
    args = parser.parse_args()
    try:
        changed = synchronize(ROOT, check=args.check)
        install_drift = check_install_consistency(ROOT)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    errors = []
    if args.check and changed:
        errors.append("Stale package metadata: " + ", ".join(changed)
                       + ". Run python scripts/sync_site_metadata.py")
    if install_drift:
        errors.append("Install command drift: " + "; ".join(install_drift))
    if errors:
        parser.exit(1, "; ".join(errors) + "\n")
    meta_msg = ", ".join(changed) if changed else "in sync"
    install_msg = "; ".join(install_drift) if install_drift else "in sync"
    print(f"Package metadata: {meta_msg} | install commands: {install_msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
