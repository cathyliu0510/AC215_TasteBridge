"""Settings for the embed stage, read from environment variables."""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DEFAULT_EXAMPLE_QUERIES = (
    "a heist with a crew of con artists",
    "a detective solving a murder in a small village",
    "a young wizard discovering hidden powers at a magic school",
)
_TRUE = {"1", "true", "yes"}
_PACKAGE_DIR = Path(__file__).resolve().parent


class ConfigError(ValueError):
    """An environment variable has an unusable value; the run stops with exit code 1."""


def _batch_size(raw: str) -> int:
    value = raw.strip()
    if not value.isdigit() or int(value) < 1:
        raise ConfigError(f"EMBED_BATCH_SIZE must be a whole number of at least 1, got {raw!r}")
    return int(value)


def _source_hash() -> str:
    """Fingerprint of this package's code, used when git is unavailable (e.g. in Docker)."""
    digest = hashlib.sha256()
    for path in sorted(_PACKAGE_DIR.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return "src-sha256:" + digest.hexdigest()[:12]


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


@dataclass(frozen=True)
class Settings:
    input_path: Path
    output_dir: Path
    model_name: str
    model_revision: str
    batch_size: int
    example_queries: tuple[str, ...]
    evidence_excerpts: bool
    code_version: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        queries = tuple(
            q.strip() for q in env.get("EMBED_EXAMPLE_QUERIES", "").split("|") if q.strip()
        )
        return cls(
            input_path=Path(env.get("EMBED_INPUT", "/data/processed/books.parquet")),
            output_dir=Path(env.get("EMBED_OUTPUT_DIR", "/data/embeddings")),
            model_name=env.get("EMBED_MODEL", DEFAULT_MODEL),
            model_revision=env.get("EMBED_MODEL_REVISION", DEFAULT_MODEL_REVISION),
            batch_size=_batch_size(env.get("EMBED_BATCH_SIZE", "64")),
            example_queries=queries or DEFAULT_EXAMPLE_QUERIES,
            evidence_excerpts=env.get("EMBED_EVIDENCE_EXCERPTS", "").strip().lower() in _TRUE,
            code_version=env.get("EMBED_CODE_VERSION") or _git_sha() or _source_hash(),
        )
