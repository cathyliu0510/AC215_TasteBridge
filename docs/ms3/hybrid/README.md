# M1 hybrid: item-kNN + ALS

Owner: **Anhad**. Code: [`src/evaluation/evaluation/hybrid.py`](../../../src/evaluation/evaluation/hybrid.py) (model) and [`tune_hybrid.py`](../../../src/evaluation/evaluation/tune_hybrid.py) (tune, then test).

**Status:** built, tested (34 new tests) and validated on synthetic data. **The Goodreads run is still to do:** `make tune-hybrid` on a machine with access to the team's DVC bucket. Until then, no claim is made that M1 beats B1 on real data.

## Why

MS2 test results on Goodreads (300 pairs, average ranking; [docs/ms2/models](../../ms2/models/README.md)):

| Model | Min-Recall@10 |
|---|---|
| B0 popularity | 0.038 |
| **B1 item-kNN** | **0.071** |
| B2 tuned ALS (served by the app) | 0.043 |

B1 is the best model, but the app can't serve it: the backend needs one vector per book. B2 is servable but scores well below B1. The MS2 analysis traced much of that gap to B2's scoring rule: work vectors are scaled to length 1 and compared by cosine. That discards vector length, which in ALS largely encodes popularity, and popularity alone scores 0.038.

M1 makes two changes and lets the tune split decide how much of each to use.

## How it works

### 1. ALS fold-in (registered as `als_foldin`)

Instead of averaging the favorites' unit vectors, M1 solves the reader's ALS vector exactly as ALS training solves a training reader's vector, treating the five favorites as that reader's likes:

```latex
x_r = \left(Y^\top Y + \alpha\, Y_F^\top Y_F + \lambda I\right)^{-1} (1+\alpha) \sum_{f \in F_r} y_f
```

Every book then scores the raw dot product, so vector length (popularity) counts:

```latex
\mathrm{ALS}_r(i) = y_i \cdot x_r
```

Y holds the raw work factors from training, F_r is the reader's five favorites, and α = 20, λ = 50 are B2's tuned values. There are no new hyperparameters. This is one 128 × 128 linear solve per reader, so it is fast enough to serve.

### 2. Blend with item-kNN (registered as `hybrid`)

```latex
s_r(i) = w \cdot \mathrm{kNN}_r(i) + (1 - w) \cdot \widetilde{\mathrm{ALS}}_r(i)
```

- kNN is B1's own score, unchanged: summed similarity to the favorites, divided by the reader's maximum, so it lies in [0, 1].
- The ALS score is min-max rescaled to [0, 1] over the books the reader didn't pick, since ALS scores can be negative.
- w = 1 gives exactly B1's lists. w = 0 is ALS alone.

The two readers' scores are then combined by average or least misery exactly as for B0–B2, and favorites are never recommended.

## Tuning protocol

The same discipline as B2's tuning:

1. Fit item-kNN (50, 100 and 200 neighbours) and ALS once, on **training readers only**.
2. Score every setting on the **tune** pairs: w ∈ {0, 0.1, …, 1} × neighbours × ALS scoring (fold-in or cosine). That is 66 settings, scored by Min-Recall@10 with average ranking and five favorites.
3. Pick the best. Ties go to the larger kNN weight, then fewer neighbours. B1's own setting (w = 1, 100 neighbours) is in the grid, so **the choice can never score below B1 on the tune split**.
4. Evaluate the choice **once** on the **test** split, next to B0, B1, B2 and ALS fold-in, with the standard evaluation.

## Run it

**Goodreads data** (needs `dvc pull` access, from the repo root):

```bash
make tune-hybrid
```

This writes two folders under `src/evaluation/results/`:
- `hybrid-<time>-tune/`: `best.json` (chosen setting), `tuning.md` (the grid as a table), `tuning.csv`, `run.log`
- `hybrid-<time>-test/`: the standard evaluation folder (`summary.md`, `config.json`, …)

To report M1 with the 1–5 favorites robustness runs, reuse the chosen setting:

```bash
make evaluate HYBRID_PARAMS=/app/results/hybrid-<time>-tune/best.json
```

**Locally, without Docker** (from `src/evaluation/`):

```bash
uv run python -m evaluation.tune_hybrid --synthetic                # invented data, about 15 s
uv run python -m evaluation.tune_hybrid --interactions ../../data/processed/interactions.parquet \
    --books ../../data/processed/books.parquet --out results
uv run pytest tests/test_hybrid.py                                  # 34 tests
```

## Synthetic validation

Invented Goodreads-shaped data near the real scale: 10,000 readers, 3,000 books, 450,317 interactions. ALS uses B2's tuned settings. Full outputs: [synthetic-run/](synthetic-run/).

**Chosen on the tune split:** w = 0.7, 50 neighbours, cosine ALS, with tune Min-Recall@10 0.0246 vs B1's 0.0233.

**Test split** (300 pairs, five favorites, ± is the 95% interval):

| Model | Min-Recall@10, average | Min-Recall@10, least misery | NDCG@10 | Long-tail coverage |
|---|---|---|---|---|
| B0 popularity | 0.0141 ± 0.0022 | 0.0141 | 0.095 | 0.000 |
| **B1 item-kNN** | **0.0284 ± 0.0035** | **0.0229** | 0.175 | 0.033 |
| B2 ALS (cosine, as served) | 0.0100 ± 0.0022 | 0.0068 | 0.087 | 0.361 |
| ALS fold-in | 0.0157 ± 0.0028 | 0.0098 | 0.116 | 0.152 |
| **M1 hybrid** | **0.0279 ± 0.0034** | 0.0145 | 0.170 | 0.058 |

What this shows, and doesn't:

- **Fold-in fixes much of B2's scoring problem.** It reached 0.0157 vs 0.0100 (+57%), and the 95% intervals don't overlap.
- **On this synthetic data, M1 ties B1.** 0.0279 vs 0.0284 is well inside the noise. The data's cluster structure is already captured by item-kNN, so ALS adds little here. That says nothing yet about Goodreads, where B2 sits much closer to B1 (0.043 vs 0.071) than it does here (0.010 vs 0.028).
- **M1 is weaker under least misery** (0.0145 vs 0.0229). If the API keeps least misery as its default, tune M1 for that aggregation too.
- **Absolute values are lower than on Goodreads** because this catalogue has 3,000 books with flatter popularity.

The same command also ran end to end on Cathy's invented raw files through her real preprocessing (`synthetic_raw.py` → `preprocess.py` → `tune_hybrid`). M1 scored 0.206 vs B1's 0.200 there, on 100 pairs (± about 0.018, so within noise).

## How to read the Goodreads run

- **Adopt M1** if it beats B1 on the test split by more than the 95% interval.
- **Otherwise keep B1 as the offline best.** Fold-in is still a cheap upgrade for the served ALS model.
- **Report as-is in both cases.** The test split is used once; don't re-tune after seeing it.

## Serving plan (MS3, not built)

The current backend serves one unit vector per book (SPEC §5). Serving M1 needs two optional files added to the artifact folder, alongside today's four:

| File | Contents | Size at 5,000 books |
|---|---|---|
| `item_factors.npy` | raw ALS work factors (float32), plus their 128 × 128 Gram matrix Y'Y | about 2.6 MB |
| `item_neighbors.npz` | each book's top-k item-kNN neighbours and similarities, sparse | about 4 MB at k = 100 |

Per request, that's one 128 × 128 solve per reader plus a sparse row sum. The map (`coords_2d.npy`) and `item_embeddings.npy` stay as they are. This needs a SPEC change agreed with Nikhil before any backend code is written.

## Files changed

| File | Change |
|---|---|
| `src/evaluation/evaluation/hybrid.py` | **new**: `ALSFoldIn`, `Hybrid`, `HybridParams`, shared model fitting |
| `src/evaluation/evaluation/tune_hybrid.py` | **new**: tune on tune split, then one test run |
| `src/evaluation/tests/test_hybrid.py` | **new**: 34 tests, e.g. fold-in equals the exact least-squares solution; w = 1 equals B1; the tuner never uses test readers |
| `src/evaluation/evaluation/als.py` | keeps raw factors (`item_factors`) beside the unit vectors; the served vectors are unchanged |
| `src/evaluation/evaluation/models.py` | registers `als_foldin` and `hybrid` |
| `src/evaluation/evaluation/run.py` | `--hybrid-*` flags; fits ALS once and shares it across models |
| `src/evaluation/tests/test_data_and_run.py` | default run now has 5 models |
| `Makefile` | `make tune-hybrid`; `HYBRID_PARAMS` for `make evaluate` |

The evaluation Docker image needs no change: no new dependencies.

## References

- Y. Hu, Y. Koren, C. Volinsky (2008). Collaborative Filtering for Implicit Feedback Datasets. ICDM. ALS and the per-reader solve used for fold-in.
- M. Deshpande, G. Karypis (2004). Item-Based Top-N Recommendation Algorithms. ACM TOIS 22(1). Item-kNN.

## AI assistance

The first version of this model, tuner and tests was drafted with Claude (Anthropic), then reviewed, run and tested by the committing team member.
