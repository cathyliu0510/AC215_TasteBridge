"""Tests for ingest.py. They serve invented gzip files over file:// URLs (no network)."""

import gzip
import json

import pytest

import ingest
from ingest import RAW_FILES, Settings, run


def _write_gz(path, n_lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for i in range(n_lines):
            handle.write(json.dumps({"i": i}) + "\n")


@pytest.fixture
def remote(tmp_path):
    """A fake 'server' folder laid out like the UCSD site, 50 lines per file."""
    root = tmp_path / "remote"
    for spec in RAW_FILES:
        _write_gz(root / spec.remote_path, 50)
    return root


def _settings(tmp_path, remote, sample_lines=0, force=False):
    return Settings(
        raw_dir=tmp_path / "raw",
        base_url=remote.as_uri(),
        sample_lines=sample_lines,
        force=force,
    )


def _count_lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def test_full_mode_copies_every_file(tmp_path, remote):
    manifest = run(_settings(tmp_path, remote))
    assert manifest["mode"] == "full"
    for spec in RAW_FILES:
        assert _count_lines(tmp_path / "raw" / spec.name) == 50
        assert manifest["files"][spec.name]["sha256"]
    assert (tmp_path / "raw" / "manifest.json").is_file()


def test_sample_mode_caps_only_interaction_files(tmp_path, remote):
    manifest = run(_settings(tmp_path, remote, sample_lines=7))
    for spec in RAW_FILES:
        n = _count_lines(tmp_path / "raw" / spec.name)
        # Interaction files are cut to 7 lines; metadata/authors stay complete.
        assert n == (7 if spec.sampled else 50)
        assert manifest["files"][spec.name]["line_cap"] == (7 if spec.sampled else 0)


def test_rerun_skips_unchanged_files(tmp_path, remote, monkeypatch):
    run(_settings(tmp_path, remote, sample_lines=7))
    calls = []
    monkeypatch.setattr(ingest, "download_full", lambda *a: calls.append(a))
    monkeypatch.setattr(ingest, "download_head", lambda *a: calls.append(a) or 0)
    run(_settings(tmp_path, remote, sample_lines=7))
    assert calls == []  # nothing downloaded twice


def test_changing_sample_size_downloads_again(tmp_path, remote):
    run(_settings(tmp_path, remote, sample_lines=7))
    manifest = run(_settings(tmp_path, remote, sample_lines=12))
    assert manifest["files"]["inter_fantasy.json.gz"]["lines"] == 12


def test_no_part_files_left_behind(tmp_path, remote):
    run(_settings(tmp_path, remote, sample_lines=5))
    assert not list((tmp_path / "raw").glob("*.part"))


def test_missing_remote_file_fails_cleanly(tmp_path, remote, monkeypatch):
    (remote / RAW_FILES[0].remote_path).unlink()
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("INGEST_BASE_URL", remote.as_uri())
    assert ingest.main() == 1  # clear error, no traceback


def test_bad_sample_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("INGEST_SAMPLE_LINES", "lots")
    with pytest.raises(ValueError):
        Settings.from_env()
