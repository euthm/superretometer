"""Large input manifests retain full coverage without one Git child per file."""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess

import pytest

capture = importlib.import_module("cognitive_harness.evidence.capture")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    (root / ".gitignore").write_text("ignored.py\n")
    names = [f"source-{i:03}.py" for i in range(128)] + ["bracket[1].py", "with space.py", "unicøde.py"]
    for name in names:
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "Synthetic index fixture"], check=True)
    return root, names


def test_git_process_count_is_constant_and_all_files_are_hashed(repo, monkeypatch):
    root, names = repo
    original = capture.git
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[1:])
        return original(*args, **kwargs)
    monkeypatch.setattr(capture, "git", counted)
    capture.observe(root, [names[0]], [])
    small_calls = len(calls)
    calls.clear()
    state = capture.observe(root, names, [".gitignore"])
    assert len(calls) == small_calls
    assert state["clean"] and state["errors"] == []
    assert [f["path"] for f in state["source_manifest"]] == sorted(names)
    assert len(state["source_manifest"]) == len(names)
    for item in state["source_manifest"]:
        raw = (root / item["path"]).read_bytes()
        assert item["size"] == len(raw)
        assert item["sha256"] == hashlib.sha256(raw).hexdigest()
    assert state["legacy_blob_digest"] == hashlib.sha256(
        b"".join((root / name).read_bytes() for name in sorted(names))
    ).hexdigest()
    assert state["lockfiles"][0]["path"] == ".gitignore"


@pytest.mark.parametrize("name", ["untracked.py", "ignored.py"])
def test_untracked_and_ignored_sources_are_still_rejected(repo, name):
    root, _ = repo
    (root / name).write_text("# not tracked\n")
    state = capture.observe(root, [name], [])
    assert f"Declared input is not tracked by Git: {name}" in state["errors"]


def test_git_pathspec_wildcards_cannot_make_an_untracked_file_look_tracked(repo):
    root, _ = repo
    # source-*.py would match 128 real index entries if passed as a Git pathspec.
    # The literal file itself must still be rejected as untracked.
    (root / "source-*.py").write_text("# untracked literal wildcard filename\n")
    state = capture.observe(root, ["source-*.py", "bracket[1].py"], [])
    assert state["errors"] == ["Declared input is not tracked by Git: source-*.py"]
