import gzip
import json

from synthetic_raw import make_raw


def test_seeded_synthetic_input_hashes_ignore_clock_and_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(gzip.time, "time", lambda: 100)
    first = make_raw(tmp_path / "first", n_works=40, n_users=50, seed=7)
    monkeypatch.setattr(gzip.time, "time", lambda: 200)
    second = make_raw(tmp_path / "second", n_works=40, n_users=50, seed=7)
    assert first["files"] == second["files"]
    for name in first["files"]:
        left, right = tmp_path / "first" / name, tmp_path / "second" / name
        assert left.read_bytes() == right.read_bytes()
        assert all(isinstance(json.loads(line), dict) for line in gzip.decompress(left.read_bytes()).splitlines())
    assert first["mode"] == second["mode"] == "synthetic"
