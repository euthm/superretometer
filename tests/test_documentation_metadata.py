"""The published static source must track the canonical package metadata."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "site_metadata", ROOT / "scripts/sync_site_metadata.py"
)
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "docs/releases").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = []\n[project]\nversion = "1.2.3"\n'
        '[tool.example]\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (tmp_path / "docs/releases/v1.2.3.md").write_text("Candidate notes", encoding="utf-8")
    for name in ("README.md", "docs/index.html"):
        (tmp_path / name).write_text(
            "Keep before\n" + metadata.START + "\nstale\n"
            + metadata.END + "\nKeep after\n", encoding="utf-8"
        )
    return tmp_path


def test_repository_metadata_is_current():
    assert metadata.synchronize(ROOT, check=True) == []


def test_drift_check_is_read_only_and_sync_preserves_other_content(checkout):
    before = (checkout / "README.md").read_bytes()
    assert metadata.synchronize(checkout, check=True) == ["README.md", "docs/index.html"]
    assert (checkout / "README.md").read_bytes() == before
    assert len(metadata.synchronize(checkout)) == 2
    for name in ("README.md", "docs/index.html"):
        text = (checkout / name).read_text(encoding="utf-8")
        assert "1.2.3" in text and "9.9.9" not in text
        assert text.startswith("Keep before\n") and text.endswith("\nKeep after\n")
    assert metadata.synchronize(checkout) == []


def test_version_change_requires_matching_notes_and_resync(checkout):
    metadata.synchronize(checkout)
    path = checkout / "pyproject.toml"
    path.write_text(path.read_text().replace("1.2.3", "1.2.4"))
    with pytest.raises(ValueError, match="Missing version notes"):
        metadata.synchronize(checkout)
    (checkout / "docs/releases/v1.2.4.md").write_text("New notes")
    assert len(metadata.synchronize(checkout, check=True)) == 2
    metadata.synchronize(checkout)
    assert "v1.2.4.md" in (checkout / "docs/index.html").read_text()


def test_missing_marker_fails_without_partial_writes(checkout):
    before = (checkout / "README.md").read_bytes()
    (checkout / "docs/index.html").write_text("No generated marker")
    with pytest.raises(ValueError, match="Expected one metadata block"):
        metadata.synchronize(checkout)
    assert (checkout / "README.md").read_bytes() == before
