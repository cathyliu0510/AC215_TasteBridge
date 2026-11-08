"""`TwoTower`: the M1 recommender, in the team evaluator's `Recommender` protocol.

The protocol (src/evaluation/evaluation/models.py) is: `name`, `items` (catalogue order),
`fit(interactions) -> self`, `score(favorites) -> np.ndarray aligned with items`.
On top of that: training checkpoints with resume, `save()` / `load()`, and `reader_vector()`
for the serving endpoint.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from twotower.data import load_content
from twotower.model import (
    ItemTower,
    TwoTowerNet,
    TwoTowerParams,
    cooc_features,
    interest_logits,
    multi_positive_loss,
    training_logits,
)

log = logging.getLogger(__name__)

LIKE_THRESHOLD = 4  # same rule as the evaluator: a rating of 4 or 5 is a like
CHECKPOINT_NAME = "last.pt"


def sample_batches(
    user_likes: list[np.ndarray], p: TwoTowerParams, rng: np.random.Generator
) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """One pass over the readers in random order.

    For each reader, k of their likes become the "favourites" (k = 5 with probability p_full,
    else uniform in 1..5) and every other like becomes a target. Yields (fav, pad, target_rows,
    target_cols): fav/pad are (B, max_favorites); targets are flat (row in batch, item index).
    """
    order = rng.permutation(len(user_likes))
    for start in range(0, len(order), p.batch_size):
        idx = order[start : start + p.batch_size]
        fav = np.zeros((len(idx), p.max_favorites), dtype=np.int64)
        pad = np.ones((len(idx), p.max_favorites), dtype=bool)
        tgt_rows, tgt_cols = [], []
        for r, u in enumerate(idx):
            liked = user_likes[u]
            k_max = min(p.max_favorites, len(liked) - 1)
            k = k_max if rng.random() < p.p_full else int(rng.integers(1, k_max + 1))
            perm = rng.permutation(liked)
            fav[r, :k], pad[r, :k] = perm[:k], False
            hidden = perm[k:]
            tgt_rows.append(np.full(len(hidden), r))
            tgt_cols.append(hidden)
        yield fav, pad, np.concatenate(tgt_rows), np.concatenate(tgt_cols)


class TwoTower:
    """Recommender protocol: name, items, fit(interactions), score(favorites)."""

    name = "two_tower"

    def __init__(
        self,
        params: TwoTowerParams | None = None,
        *,
        content_paths: dict[str, Any] | None = None,
        tune_fn: Callable[[TwoTower], float] | None = None,
        log_fn: Callable[[dict[str, Any]], None] | None = None,
        checkpoint_dir: str | Path | None = None,
        checkpoint_every: int = 10,
        resume: bool = False,
    ):
        self.p = params or TwoTowerParams()
        self.content_paths = content_paths
        self.tune_fn = tune_fn  # returns a TUNE-split score, higher is better
        self.log_fn = log_fn or (lambda row: log.info(json.dumps(row)))
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        self.checkpoint_every = checkpoint_every
        self.resume = resume
        self.items: tuple[str, ...] = ()
        self._row: dict[str, int] = {}
        self.history: list[dict[str, Any]] = []
        self.missing_content = 0
        self.best_tune: float | None = None
        self.net: TwoTowerNet | None = None
        self._tok: torch.Tensor | None = None
        self._z: torch.Tensor | None = None
        self._user_likes: list[np.ndarray] = []

    # ------------------------------------------------------------------ build
    def prepare(self, interactions: pd.DataFrame) -> TwoTower:
        """Fix the catalogue (every liked work in `interactions`) and build an untrained net."""
        if self.content_paths is None:
            raise ValueError("TwoTower needs content_paths (books, MiniLM embeddings, rows) to build items")
        p = self.p
        torch.manual_seed(p.seed)
        liked = interactions[interactions["rating"] >= LIKE_THRESHOLD]
        self.items = tuple(sorted(liked["work_id"].astype(str).unique()))
        self._row = {w: i for i, w in enumerate(self.items)}
        row_of, emb, genre_of, n_genres = load_content(**self.content_paths)
        zero = np.zeros(emb.shape[1], dtype=np.float32)
        self.missing_content = sum(w not in row_of for w in self.items)
        if self.missing_content:
            log.warning("%d catalogue items have no description vector; using zeros", self.missing_content)
        content = torch.tensor(np.stack([emb[row_of[w]] if w in row_of else zero for w in self.items]))
        genres = torch.tensor([genre_of.get(w, n_genres - 1) for w in self.items])
        groups = liked.assign(i=liked["work_id"].astype(str).map(self._row)).groupby("user_id")["i"]
        self._user_likes = [g.to_numpy() for _, g in groups if len(g) >= 2]
        if not self._user_likes:
            raise ValueError("no reader has two or more likes; nothing to train on")
        device = p.resolved_device()
        n = len(self.items)
        cooc = cooc_features(self._user_likes, n, p.cooc_dim, device, p.seed) if p.cooc_dim > 0 else None
        self.net = TwoTowerNet(content, genres, n_genres, p, cooc).to(device)
        self._cache()
        return self

    # ------------------------------------------------------------------ training
    def fit(self, interactions: pd.DataFrame) -> TwoTower:
        p = self.p
        rng = np.random.default_rng(p.seed)
        self.prepare(interactions)
        net = self._require_net()
        device = next(net.parameters()).device
        user_likes, n = self._user_likes, len(self.items)
        pop = np.bincount(np.concatenate(user_likes), minlength=n).astype(np.float32) + 1.0
        logq = torch.from_numpy(np.log(pop / pop.sum())).to(device)
        opt = torch.optim.AdamW(net.parameters(), lr=p.lr, weight_decay=p.weight_decay)
        steps_per_epoch = math.ceil(len(user_likes) / p.batch_size) * p.repeats
        total = steps_per_epoch * p.epochs
        # 10% warm-up; very short runs (tests, smoke jobs) need at least two warm-up steps
        sched = torch.optim.lr_scheduler.OneCycleLR(
            opt, max_lr=p.lr, total_steps=total, pct_start=min(0.5, max(0.1, 2.0 / total))
        )
        state: dict[str, Any] = {"epoch": 0, "step": 0, "best": -1.0, "best_state": None, "bad": 0}
        ckpt = self._checkpoint_path()
        if self.resume and ckpt is not None and ckpt.exists():
            state = self._load_checkpoint(opt, sched, rng)
            log.info("resumed from %s at epoch %d", ckpt, state["epoch"])

        for epoch in range(state["epoch"] + 1, p.epochs + 1):
            if self.tune_fn and state["bad"] >= p.patience:
                break  # a resumed run that had already early-stopped
            net.train()
            tic, losses = time.perf_counter(), []
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            for _ in range(p.repeats):
                for fav, pad, tr, tc in sample_batches(user_likes, p, rng):
                    logits = training_logits(net, fav, pad, logq, p.pop_beta)
                    loss = multi_positive_loss(logits, tr, tc)
                    opt.zero_grad(set_to_none=True)
                    loss.backward()
                    nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                    opt.step()
                    sched.step()
                    state["step"] += 1
                    losses.append(loss.item())
            row: dict[str, Any] = {
                "epoch": epoch,
                "step": state["step"],
                "train/loss": float(np.mean(losses)),
                "lr": sched.get_last_lr()[0],
                "epoch_seconds": round(time.perf_counter() - tic, 2),
            }
            if device.type == "cuda":
                row["gpu/max_memory_mb"] = round(torch.cuda.max_memory_allocated(device) / 2**20, 1)
            if self.tune_fn and (epoch % p.eval_every == 0 or epoch == p.epochs):
                self._cache()
                score = self.tune_fn(self)
                row["tune/min_recall@10"] = score
                if score > state["best"]:
                    state["best"], state["bad"] = score, 0
                    state["best_state"] = {k: v.detach().clone() for k, v in net.state_dict().items()}
                    row["best"] = True
                else:
                    state["bad"] += 1
            state["epoch"] = epoch
            self.history.append(row)
            self.log_fn(row)
            stop = bool(self.tune_fn) and state["bad"] >= p.patience
            if self.checkpoint_dir and (epoch % self.checkpoint_every == 0 or stop or epoch == p.epochs):
                self._save_checkpoint(state, opt, sched, rng)
            if stop:
                break
        if state["best_state"] is not None:
            net.load_state_dict(state["best_state"])
            self.best_tune = float(state["best"])
        self._cache()
        return self

    # ------------------------------------------------------------------ checkpoints
    def _checkpoint_path(self) -> Path | None:
        return self.checkpoint_dir / CHECKPOINT_NAME if self.checkpoint_dir else None

    def _save_checkpoint(
        self,
        state: dict[str, Any],
        opt: torch.optim.Optimizer,
        sched: torch.optim.lr_scheduler.LRScheduler,
        rng: np.random.Generator,
    ) -> None:
        """Everything needed to continue exactly: weights, optimiser, schedule, both RNGs, best-so-far."""
        path = self._checkpoint_path()
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = {
            **state,
            "net": self._require_net().state_dict(),
            "opt": opt.state_dict(),
            "sched": sched.state_dict(),
            "np_rng": rng.bit_generator.state,
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
            "history": self.history,
            "params": self.p.as_dict(),
        }
        tmp = path.with_suffix(".tmp")
        torch.save(blob, tmp)
        os.replace(tmp, path)  # atomic: a preempted job never leaves a half-written checkpoint

    def _load_checkpoint(
        self, opt: torch.optim.Optimizer, sched: torch.optim.lr_scheduler.LRScheduler, rng: np.random.Generator
    ) -> dict[str, Any]:
        path = self._checkpoint_path()
        assert path is not None
        blob = torch.load(path, map_location=next(self._require_net().parameters()).device, weights_only=False)
        self._require_net().load_state_dict(blob["net"])
        opt.load_state_dict(blob["opt"])
        sched.load_state_dict(blob["sched"])
        rng.bit_generator.state = blob["np_rng"]
        torch.set_rng_state(blob["torch_rng"].cpu())
        if blob["cuda_rng"] is not None and torch.cuda.is_available():
            torch.cuda.set_rng_state_all([s.cpu() for s in blob["cuda_rng"]])
        self.history = list(blob["history"])
        return {k: blob[k] for k in ("epoch", "step", "best", "best_state", "bad")}

    # ------------------------------------------------------------------ scoring
    def _require_net(self) -> TwoTowerNet:
        if self.net is None:
            raise RuntimeError("model is not built; call fit(), prepare() or TwoTower.load() first")
        return self.net

    @torch.no_grad()
    def _cache(self) -> None:
        net = self._require_net()
        net.eval()
        tok = net.items.tokens()
        self._tok, self._z = tok, ItemTower.vectors(tok)

    @torch.no_grad()
    def reader_vector(self, favorites: Sequence[str]) -> torch.Tensor | None:
        """u for known favourites (first max_favorites of them): (L, d) for "multi", (d,) for "cls"."""
        rows = [self._row[w] for w in favorites if w in self._row][: self.p.max_favorites]
        if not rows or self._tok is None:
            return None
        device = self._tok.device
        fav = torch.tensor([rows], device=device)
        pad = torch.zeros(1, len(rows), dtype=torch.bool, device=device)
        return self._require_net().reader(self._tok[fav], pad)[0]

    @torch.no_grad()
    def score(self, favorites: Sequence[str]) -> np.ndarray:
        """One score per catalogue item, aligned with `items`. Unknown favourites are ignored."""
        u = self.reader_vector(favorites)
        if u is None or self._z is None:
            return np.zeros(len(self.items))
        if u.dim() == 1:
            return (self._z @ u).float().cpu().numpy().astype(float)  # cosine
        tau = self._require_net().tau
        # tau * logsumexp_j cos(u_j, z) / tau: a soft maximum of cosines, on the cosine scale
        return (tau * interest_logits(u[None], self._z, None, tau)[0]).float().cpu().numpy().astype(float)

    def item_vectors(self) -> np.ndarray:
        """z for every item, (N, d) float32, unit rows: the backend's item_embeddings.npy."""
        if self._z is None:
            raise RuntimeError("model is not built")
        return self._z.float().cpu().numpy().astype(np.float32)

    # ------------------------------------------------------------------ persistence
    def save(self, out: str | Path, extra_meta: dict[str, Any] | None = None) -> Path:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        torch.save(self._require_net().state_dict(), out / "two_tower.pt")
        np.save(out / "item_embeddings.npy", self.item_vectors())
        (out / "items.json").write_text(json.dumps(list(self.items)))
        meta = {**self.p.as_dict(), "best_tune_min_recall@10": self.best_tune, **(extra_meta or {})}
        (out / "params.json").write_text(json.dumps(meta, indent=2))
        return out

    @classmethod
    def load(cls, model_dir: str | Path, device: str = "auto") -> TwoTower:
        """Rebuild from save(): no data files are needed, the frozen inputs live in the state dict."""
        model_dir = Path(model_dir)
        params = TwoTowerParams.from_dict(json.loads((model_dir / "params.json").read_text()))
        params.device = device
        state = torch.load(model_dir / "two_tower.pt", map_location="cpu", weights_only=True)
        n, c = state["items.content"].shape
        n_genres = state["items.genre_emb.weight"].shape[0]
        cooc = torch.zeros_like(state["items.cooc"]) if "items.cooc" in state else None
        net = TwoTowerNet(torch.zeros(n, c), torch.zeros(n, dtype=torch.long), n_genres, params, cooc)
        net.load_state_dict(state)
        self = cls(params)
        self.items = tuple(json.loads((model_dir / "items.json").read_text()))
        if len(self.items) != n:
            raise ValueError(f"items.json has {len(self.items)} ids but the weights have {n} items")
        self._row = {w: i for i, w in enumerate(self.items)}
        self.net = net.to(params.resolved_device())
        self._cache()
        return self
