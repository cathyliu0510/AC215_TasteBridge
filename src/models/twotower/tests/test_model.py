"""Invariants of the network and of `score()`. "Runs != works" (L13): these prove the wiring,
not the quality; quality is the evaluator's job."""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from twotower import TwoTower, TwoTowerParams
from twotower.model import interest_logits, training_logits

FAVS = ["w01", "w05", "w12"]


def test_item_and_interest_vectors_are_unit_length(tiny_model: TwoTower) -> None:
    z = torch.from_numpy(tiny_model.item_vectors())
    torch.testing.assert_close(z.norm(dim=1), torch.ones(len(tiny_model.items)))
    u = tiny_model.reader_vector(FAVS)
    assert u is not None and u.shape == (3, 16)
    torch.testing.assert_close(u.norm(dim=-1), torch.ones(3))


def test_zero_init_readout_starts_as_the_favourites_themselves(tiny_data, tiny_params) -> None:
    data, inter = tiny_data
    model = TwoTower(tiny_params, content_paths=data.content_paths()).prepare(inter)
    u = model.reader_vector(FAVS)
    assert model._tok is not None and u is not None
    rows = [model.items.index(w) for w in FAVS]
    torch.testing.assert_close(u, F.normalize(model._tok[rows], dim=-1))


def test_permutation_invariance(tiny_model: TwoTower) -> None:
    """The reader tower encodes a SET: order of favourites must not matter."""
    np.testing.assert_allclose(tiny_model.score(FAVS), tiny_model.score(FAVS[::-1]), rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(
        tiny_model.score(FAVS), tiny_model.score([FAVS[1], FAVS[2], FAVS[0]]), rtol=1e-5, atol=1e-6
    )


def test_padding_invariance(tiny_model: TwoTower) -> None:
    """[a, b, c] and [a, b, c, PAD, PAD] give the same interest vectors and logits."""
    net, tok, z = tiny_model._require_net(), tiny_model._tok, tiny_model._z
    assert tok is not None and z is not None
    rows = [tiny_model.items.index(w) for w in FAVS]
    with torch.no_grad():
        plain = net.reader(tok[torch.tensor([rows])], torch.zeros(1, 3, dtype=torch.bool))
        padded_pad = torch.tensor([[False, False, False, True, True]])
        padded = net.reader(tok[torch.tensor([rows + [0, 0]])], padded_pad)
        torch.testing.assert_close(padded[:, :3], plain, rtol=1e-5, atol=1e-6)
        torch.testing.assert_close(
            interest_logits(padded, z, padded_pad, 0.1), interest_logits(plain, z, None, 0.1), rtol=1e-5, atol=1e-5
        )


def test_favourites_are_masked_in_training_logits(tiny_model: TwoTower) -> None:
    fav = np.array([[1, 5, 12, 0, 0], [3, 0, 0, 0, 0]], dtype=np.int64)
    pad = np.array([[False, False, False, True, True], [False, True, True, True, True]])
    logits = training_logits(tiny_model._require_net(), fav, pad)
    assert torch.isneginf(logits[0, [1, 5, 12]]).all() and torch.isneginf(logits[1, 3])
    assert torch.isfinite(logits[0, 0]), "a padded slot must not mask item 0"
    assert torch.isfinite(logits).sum() == logits.numel() - 4


def test_single_favourite_equals_plain_cosine(tiny_model: TwoTower) -> None:
    u = tiny_model.reader_vector(["w07"])
    assert u is not None and tiny_model._z is not None
    np.testing.assert_allclose(tiny_model.score(["w07"]), (tiny_model._z @ u[0]).numpy(), rtol=1e-5, atol=1e-6)


def test_score_is_a_soft_maximum_of_cosines(tiny_model: TwoTower) -> None:
    """max_j cos(u_j, z) <= s <= max_j cos(u_j, z) + tau * log L."""
    u = tiny_model.reader_vector(FAVS)
    assert u is not None and tiny_model._z is not None
    hard = (u @ tiny_model._z.T).max(dim=0).values.numpy()
    s = tiny_model.score(FAVS)
    tau = tiny_model.p.tau
    assert np.all(s >= hard - 1e-6)
    assert np.all(s <= hard + tau * math.log(len(FAVS)) + 1e-6)


def test_cls_readout_scores_are_cosines(tiny_data, tiny_params) -> None:
    data, inter = tiny_data
    tiny_params.readout = "cls"
    model = TwoTower(tiny_params, content_paths=data.content_paths()).prepare(inter)
    u = model.reader_vector(FAVS)
    assert u is not None and u.shape == (16,)
    s = model.score(FAVS)
    assert np.all(np.abs(s) <= 1 + 1e-6)


def test_score_shape_order_and_unknown_favourites(tiny_model: TwoTower) -> None:
    s = tiny_model.score(FAVS)
    assert s.shape == (len(tiny_model.items),) and s.dtype == np.float64
    assert list(tiny_model.items) == sorted(tiny_model.items)
    np.testing.assert_allclose(tiny_model.score(FAVS + ["not-a-book"]), s)
    np.testing.assert_array_equal(tiny_model.score(["nope", "also-nope"]), np.zeros(len(tiny_model.items)))
    np.testing.assert_array_equal(tiny_model.score([]), np.zeros(len(tiny_model.items)))


def test_only_the_first_max_favourites_are_used(tiny_model: TwoTower) -> None:
    seven = [f"w{i:02d}" for i in range(7)]
    np.testing.assert_allclose(tiny_model.score(seven), tiny_model.score(seven[:5]))


def test_deterministic_in_eval_mode(tiny_model: TwoTower) -> None:
    np.testing.assert_array_equal(tiny_model.score(FAVS), tiny_model.score(FAVS))


def test_params_override_and_round_trip() -> None:
    p = TwoTowerParams().override(["tau=0.2", "mean_skip=true", "readout=cls", "layers=3"])
    assert (p.tau, p.mean_skip, p.readout, p.layers) == (0.2, True, "cls", 3)
    assert TwoTowerParams.from_dict({**p.as_dict(), "fit_seconds": 1.0}) == p
    with pytest.raises(ValueError):
        TwoTowerParams().override(["no_such_field=1"])
    with pytest.raises(ValueError):
        TwoTowerParams().override(["readout=bogus"])
    with pytest.raises(ValueError):
        TwoTowerParams(dim=10, heads=4)
