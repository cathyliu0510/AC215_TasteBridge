"""Experiment tracking: always a local JSONL file, plus W&B when a key is available.

Lecture 13 (s.37-47): secret -> login -> init -> log. The W&B API key is looked up in this
order, and is never written to the config, the logs or the image:

1. the WANDB_API_KEY environment variable (local runs: `-e WANDB_API_KEY=...`);
2. a key file (`--wandb-key-file ../secrets/wandb.key`);
3. a Secret Manager version (`--wandb-secret projects/P/secrets/wandb-api-key/versions/latest`),
   read with the job's service account on Vertex AI.

`WANDB_MODE=offline` needs no key: runs go to ./wandb and can be uploaded later with
`wandb sync`. Reader ids and per-pair rows are never sent to W&B.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def read_secret(name: str) -> str:
    """Payload of a Secret Manager version, e.g. projects/P/secrets/S/versions/latest."""
    from google.cloud import secretmanager  # imported lazily: only cloud runs need it

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()


def resolve_wandb_key(key_file: str | None = None, secret: str | None = None) -> str | None:
    if os.environ.get("WANDB_API_KEY"):
        return os.environ["WANDB_API_KEY"].strip()
    if key_file:
        return Path(key_file).read_text().strip()
    if secret:
        return read_secret(secret)
    return None


def wandb_dir(run_dir: Path) -> str:
    """W&B keeps many small, constantly rewritten files: keep them off the /gcs FUSE mount on Vertex."""
    if os.environ.get("WANDB_DIR"):
        return os.environ["WANDB_DIR"]
    return "/tmp" if run_dir.as_posix().startswith("/gcs/") else str(run_dir)


class Tracker:
    """mode: "auto" (W&B if a key or WANDB_MODE=offline/disabled, else JSONL only), "wandb", "off"."""

    def __init__(
        self,
        run_dir: str | Path,
        run_id: str,
        config: dict[str, Any],
        *,
        mode: str = "auto",
        project: str | None = None,
        entity: str | None = None,
        key_file: str | None = None,
        secret: str | None = None,
    ):
        if mode not in ("auto", "wandb", "off"):
            raise ValueError(f"tracker mode must be auto, wandb or off, got {mode!r}")
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))
        self._jsonl = (self.run_dir / "tracking.jsonl").open("a", encoding="utf-8")
        self._summary: dict[str, Any] = {}
        self.run: Any = None
        if mode == "off":
            return
        wandb_mode = os.environ.get("WANDB_MODE", "online")
        key = None if wandb_mode in ("offline", "disabled") else resolve_wandb_key(key_file, secret)
        if key is None and wandb_mode not in ("offline", "disabled"):
            if mode == "wandb":
                raise RuntimeError(
                    "tracker=wandb but no W&B key: set WANDB_API_KEY, --wandb-key-file or --wandb-secret"
                )
            log.info("no W&B key found; tracking to %s only", self.run_dir / "tracking.jsonl")
            return
        import wandb

        if key is not None:
            wandb.login(key=key)
        self.run = wandb.init(
            project=project or os.environ.get("WANDB_PROJECT", "tastebridge-two-tower"),
            entity=entity or os.environ.get("WANDB_ENTITY") or None,
            name=run_id,
            config=config,
            dir=wandb_dir(self.run_dir),
            job_type="train",
        )
        log.info("W&B run: %s", getattr(self.run, "url", None) or f"(mode={wandb_mode})")

    @property
    def url(self) -> str | None:
        return getattr(self.run, "url", None) if self.run is not None else None

    def log(self, row: dict[str, Any]) -> None:
        self._jsonl.write(json.dumps(row) + "\n")
        self._jsonl.flush()
        if self.run is not None:
            self.run.log(row, step=row.get("step"))

    def summary(self, values: dict[str, Any]) -> None:
        self._summary.update(values)
        (self.run_dir / "summary.json").write_text(json.dumps(self._summary, indent=2, default=str))
        if self.run is not None:
            self.run.summary.update(values)

    def artifact(self, path: str | Path, name: str, kind: str, metadata: dict[str, Any] | None = None) -> None:
        """Upload a file or folder as a W&B artifact (lecture 13 [31:53]); no-op without W&B."""
        if self.run is None:
            return
        import wandb

        art = wandb.Artifact(name=name, type=kind, metadata=metadata or {})
        p = Path(path)
        if p.is_dir():
            art.add_dir(str(p))
        else:
            art.add_file(str(p))
        self.run.log_artifact(art)

    def finish(self) -> None:
        self._jsonl.close()
        if self.run is not None:
            self.run.finish()
