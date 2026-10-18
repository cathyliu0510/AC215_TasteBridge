from pathlib import Path

from embed.config import DEFAULT_EXAMPLE_QUERIES, DEFAULT_MODEL, DEFAULT_MODEL_REVISION, Settings


def test_defaults():
    s = Settings.from_env({"EMBED_CODE_VERSION": "abc"})
    assert s.input_path == Path("/data/processed/books.parquet")
    assert s.output_dir == Path("/data/embeddings")
    assert s.model_name == DEFAULT_MODEL == "sentence-transformers/all-MiniLM-L6-v2"
    assert s.model_revision == DEFAULT_MODEL_REVISION == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert s.batch_size == 64
    assert s.example_queries == DEFAULT_EXAMPLE_QUERIES
    assert len(DEFAULT_EXAMPLE_QUERIES) == 3
    assert s.evidence_excerpts is False
    assert s.code_version == "abc"


def test_overrides():
    s = Settings.from_env(
        {
            "EMBED_INPUT": "in.parquet",
            "EMBED_OUTPUT_DIR": "out",
            "EMBED_MODEL": "m",
            "EMBED_MODEL_REVISION": "r",
            "EMBED_BATCH_SIZE": "8",
            "EMBED_EXAMPLE_QUERIES": " heist |  | murder in a village ",
            "EMBED_EVIDENCE_EXCERPTS": "true",
            "EMBED_CODE_VERSION": "abc",
        }
    )
    assert s.input_path == Path("in.parquet")
    assert s.output_dir == Path("out")
    assert (s.model_name, s.model_revision, s.batch_size) == ("m", "r", 8)
    assert s.example_queries == ("heist", "murder in a village")
    assert s.evidence_excerpts is True


import pytest

from embed import config
from embed.config import ConfigError


@pytest.mark.parametrize("value", ["abc", "0", "-3", "2.5", ""])
def test_bad_batch_size_is_a_clear_error(value):
    with pytest.raises(ConfigError, match="EMBED_BATCH_SIZE"):
        Settings.from_env({"EMBED_BATCH_SIZE": value, "EMBED_CODE_VERSION": "abc"})


def test_code_version_falls_back_to_source_hash_without_git(monkeypatch):
    monkeypatch.setattr(config, "_git_sha", lambda: None)
    first = Settings.from_env({}).code_version
    assert first.startswith("src-sha256:") and len(first) == len("src-sha256:") + 12
    assert Settings.from_env({}).code_version == first  # deterministic
