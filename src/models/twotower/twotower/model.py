"""The M1 network: an item tower, a set-Transformer reader tower, and the scoring rule.

Item tower  f(i):  [MiniLM description vector e_i (384, frozen) -> Linear 384->d]
                   + learned ID embedding v_i (d) + genre embedding (d)
                   -> residual MLP -> h_i (d)        ("item token")
                   -> L2-normalise -> z_i (d)        ("item vector")
Reader tower g(S): [CLS] + item tokens h_j of the reader's favourites (a SET: no positions)
                   -> L-layer pre-LN Transformer encoder with a key-padding mask -> readout:
                     "multi" (default): per favourite j, u_j = l2(h_j/|h_j| + W_o LN(y_j))
                     "cls":             u   = l2(W_o LN(y_CLS))  [+ mean of favourites if mean_skip]
Score       s(S, i) = tau * logsumexp_j (u_j . z_i / tau)     (= cos(u, z_i) for "cls")

See doc/ms3-two-tower/figures/two_tower_architecture.pdf for the diagram.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class TwoTowerParams:
    """Every knob of M1. Defaults are the best local configuration (doc/ms3-two-tower/results)."""

    dim: int = 128  # d: item/reader vector length (same as the ALS export)
    id_dim_dropout: float = 0.2  # drop an item's ID embedding sometimes, so content must carry signal
    layers: int = 2  # Transformer encoder layers in the reader tower
    heads: int = 4
    ffn: int = 256
    dropout: float = 0.1
    tau: float = 0.1  # softmax temperature on cosine scores
    max_favorites: int = 5  # the app asks for five favourites
    p_full: float = 0.3  # share of training samples that use all five favourites
    batch_size: int = 128
    epochs: int = 150
    lr: float = 1e-3
    weight_decay: float = 1e-4
    eval_every: int = 5  # epochs between TUNE evaluations
    patience: int = 6  # TUNE evaluations without improvement before early stopping
    cooc_dim: int = 0  # >0: frozen collaborative item feature (rank-k SVD of the TRAIN item-kNN matrix)
    readout: str = "multi"  # "multi": one interest vector per favourite; "cls": one reader vector
    mean_skip: bool = False  # "cls" only: add the mean of the favourites' item vectors
    pop_beta: float = 0.0  # logQ correction: subtract beta*log(popularity) from TRAINING logits
    repeats: int = 1  # passes over the readers per epoch (fresh favourite samples each pass)
    seed: int = 42
    device: str = "auto"  # "auto" = cuda if available, else cpu

    def __post_init__(self) -> None:
        if self.readout not in ("multi", "cls"):
            raise ValueError(f"readout must be 'multi' or 'cls', got {self.readout!r}")
        if self.dim % self.heads:
            raise ValueError(f"dim ({self.dim}) must be divisible by heads ({self.heads})")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def resolved_device(self) -> torch.device:
        if self.device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(self.device)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> TwoTowerParams:
        """Build from a saved params.json; ignores keys that are not fields (e.g. run metadata)."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def override(self, assignments: list[str]) -> TwoTowerParams:
        """Apply `field=value` strings (the CLI's --set), casting to the field's type."""
        for item in assignments:
            key, sep, raw = item.partition("=")
            if not sep or not hasattr(self, key):
                raise ValueError(f"--set expects field=value with a TwoTowerParams field, got {item!r}")
            current = getattr(self, key)
            value: Any
            if isinstance(current, bool):
                value = raw.strip().lower() in ("1", "true", "yes")
            else:
                value = type(current)(raw)
            setattr(self, key, value)
        self.__post_init__()
        return self


class ItemTower(nn.Module):
    """h_i = x_i + MLP(x_i), with x_i = W_c e_i + genre_i + id_i (+ W_k cooc_i)."""

    content: torch.Tensor
    genre_ids: torch.Tensor
    cooc: torch.Tensor

    def __init__(
        self,
        content: torch.Tensor,
        genre_ids: torch.Tensor,
        n_genres: int,
        p: TwoTowerParams,
        cooc: torch.Tensor | None = None,
    ):
        super().__init__()
        n, c = content.shape
        self.has_cooc = cooc is not None
        if cooc is not None:
            self.register_buffer("cooc", cooc)  # (N, cooc_dim), frozen, TRAIN-only
            self.cooc_proj = nn.Linear(cooc.shape[1], p.dim)
        self.register_buffer("content", content)  # (N, 384), frozen MiniLM
        self.register_buffer("genre_ids", genre_ids)  # (N,)
        self.content_proj = nn.Linear(c, p.dim)
        self.id_emb = nn.Embedding(n, p.dim)
        nn.init.normal_(self.id_emb.weight, std=0.02)
        self.genre_emb = nn.Embedding(n_genres, p.dim)
        self.mlp = nn.Sequential(
            nn.LayerNorm(p.dim),
            nn.Linear(p.dim, 2 * p.dim),
            nn.GELU(),
            nn.Dropout(p.dropout),
            nn.Linear(2 * p.dim, p.dim),
        )
        self.id_drop = p.id_dim_dropout

    def tokens(self) -> torch.Tensor:
        """h_i for every item, shape (N, d): the representation both towers share."""
        x = self.content_proj(self.content) + self.genre_emb(self.genre_ids)
        if self.has_cooc:
            x = x + self.cooc_proj(self.cooc)
        idv = self.id_emb.weight
        if self.training and self.id_drop > 0:
            keep = (torch.rand(idv.shape[0], 1, device=idv.device) > self.id_drop).float()
            idv = idv * keep
        x = x + idv
        return x + self.mlp(x)

    @staticmethod
    def vectors(tokens: torch.Tensor) -> torch.Tensor:
        """z_i = h_i / |h_i|."""
        return F.normalize(tokens, dim=-1)


class ReaderTower(nn.Module):
    """A set encoder over the favourites' item tokens (no positional encoding)."""

    def __init__(self, p: TwoTowerParams):
        super().__init__()
        self.cls = nn.Parameter(torch.zeros(1, 1, p.dim))
        nn.init.normal_(self.cls, std=0.02)
        layer = nn.TransformerEncoderLayer(
            p.dim, p.heads, p.ffn, p.dropout, activation="gelu", batch_first=True, norm_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, p.layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(p.dim)
        self.out = nn.Linear(p.dim, p.dim)
        self.mean_skip = p.mean_skip
        self.readout = p.readout
        if p.mean_skip or p.readout == "multi":
            # Zero-init W_o: the tower starts as "your favourites themselves" and learns a correction.
            nn.init.zeros_(self.out.weight)
            nn.init.zeros_(self.out.bias)

    def forward(self, fav_tokens: torch.Tensor, pad: torch.Tensor) -> torch.Tensor:
        """fav_tokens (B, L, d); pad (B, L), True where padded.

        Returns unit vectors: (B, L, d) for "multi" (padded rows are meaningless and must be
        masked by the caller), (B, d) for "cls".
        """
        b = fav_tokens.shape[0]
        x = torch.cat([self.cls.expand(b, -1, -1), fav_tokens], dim=1)
        mask = torch.cat([torch.zeros(b, 1, dtype=torch.bool, device=pad.device), pad], dim=1)
        y = self.encoder(x, src_key_padding_mask=mask)
        if self.readout == "multi":
            return F.normalize(F.normalize(fav_tokens, dim=-1) + self.out(self.norm(y[:, 1:])), dim=-1)
        out = self.out(self.norm(y[:, 0]))
        if self.mean_skip:
            keep = (~pad).unsqueeze(-1).float()
            out = out + (F.normalize(fav_tokens, dim=-1) * keep).sum(1) / keep.sum(1).clamp(min=1)
        return F.normalize(out, dim=-1)


def interest_logits(u: torch.Tensor, z: torch.Tensor, pad: torch.Tensor | None, tau: float) -> torch.Tensor:
    """cos(u, z)/tau for u (B, d); for multi-interest u (B, L, d): logsumexp over the L interests.

    Returns (B, N). Multiply by tau to get the score s(S, i).
    """
    if u.dim() == 2:
        return (u @ z.T) / tau
    per = torch.einsum("bld,nd->bln", u, z) / tau  # (B, L, N)
    if pad is not None:
        per = per.masked_fill(pad.unsqueeze(-1), float("-inf"))
    return torch.logsumexp(per, dim=1)


class TwoTowerNet(nn.Module):
    def __init__(
        self,
        content: torch.Tensor,
        genre_ids: torch.Tensor,
        n_genres: int,
        p: TwoTowerParams,
        cooc: torch.Tensor | None = None,
    ):
        super().__init__()
        self.items = ItemTower(content, genre_ids, n_genres, p, cooc)
        self.reader = ReaderTower(p)
        self.tau = p.tau

    def forward(self, fav_idx: torch.Tensor, pad: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        tok = self.items.tokens()  # (N, d)
        z = ItemTower.vectors(tok)  # (N, d)
        u = self.reader(tok[fav_idx], pad)  # (B, L, d) or (B, d)
        return u, z


def favourite_mask(fav: np.ndarray, pad: np.ndarray, n: int, device: torch.device) -> torch.Tensor:
    """(B, N) boolean mask, True at each sample's own favourites (they are not valid targets)."""
    m = torch.zeros(len(fav), n, dtype=torch.bool, device=device)
    r, c = np.nonzero(~pad)
    m[torch.from_numpy(r).to(device), torch.from_numpy(fav[r, c]).to(device)] = True
    return m


def training_logits(
    net: TwoTowerNet,
    fav: np.ndarray,
    pad: np.ndarray,
    logq: torch.Tensor | None = None,
    pop_beta: float = 0.0,
) -> torch.Tensor:
    """Full-catalogue logits for a batch, with favourites set to -inf. Shape (B, N)."""
    device = next(net.parameters()).device
    fav_t = torch.from_numpy(fav).to(device)
    pad_t = torch.from_numpy(pad).to(device)
    u, z = net(fav_t, pad_t)
    logits = interest_logits(u, z, pad_t, net.tau)
    if pop_beta and logq is not None:
        logits = logits - pop_beta * logq
    return logits.masked_fill(favourite_mask(fav, pad, z.shape[0], device), float("-inf"))


def multi_positive_loss(logits: torch.Tensor, target_rows: np.ndarray, target_cols: np.ndarray) -> torch.Tensor:
    """Softmax cross-entropy averaged over each reader's hidden likes, then over readers."""
    device = logits.device
    logp = F.log_softmax(logits, dim=-1)
    tr = torch.from_numpy(target_rows).to(device)
    tc = torch.from_numpy(target_cols).to(device)
    per = -logp[tr, tc]
    counts = torch.bincount(tr, minlength=logits.shape[0]).clamp(min=1).float()
    return (torch.zeros(logits.shape[0], device=device).index_add_(0, tr, per) / counts).mean()


@torch.no_grad()
def cooc_features(
    user_likes: list[np.ndarray], n: int, k: int, device: torch.device, seed: int, neighbors: int = 100
) -> torch.Tensor:
    """TRAIN-only item-item cosine (B1's matrix), top-`neighbors` per row, symmetrised, rank-k SVD."""
    rows = np.concatenate([np.full(len(lk), u) for u, lk in enumerate(user_likes)])
    cols = np.concatenate(user_likes)
    x = torch.zeros(len(user_likes), n, device=device)
    x[torch.from_numpy(rows).to(device), torch.from_numpy(cols).to(device)] = 1.0
    co = x.T @ x
    d = co.diagonal().clamp(min=1).sqrt()
    sim = co / d[:, None] / d[None, :]
    sim.fill_diagonal_(0)
    thr = sim.topk(min(neighbors, n - 1), dim=1).values[:, -1:]
    sim = torch.where(sim >= thr, sim, torch.zeros_like(sim))
    sim = torch.maximum(sim, sim.T)
    torch.manual_seed(seed)
    u, s, _ = torch.svd_lowrank(sim, q=k, niter=6)
    feat = u * s.sqrt()
    return (feat / feat.norm(dim=1, keepdim=True).clamp(min=1e-6)).cpu()
