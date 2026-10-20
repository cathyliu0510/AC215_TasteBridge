# TasteBridge evaluation

Offline pair simulation from the [MS1 proposal](../../milestones/ms1/source/sections/07_evaluation.tex). Goodreads records no joint choices, so we build simulated reader pairs from individual histories and check whether a shared list recovers works each reader liked but the model never saw.

## Run it

**Docker (from the repo root, one command):**

```bash
mkdir -p src/evaluation/results          # the container writes here
docker compose --profile evaluation run --rm evaluation
```

With no data mounted this runs on synthetic data, with 1–5 favorites per reader. Results land in `src/evaluation/results/<run_id>/`.

**Real data:** put the preprocessed tables in `src/evaluation/data/` (git-ignored, mounted read-only), then:

```bash
docker compose --profile evaluation run --rm evaluation \
  --interactions /app/data/interactions.parquet --books /app/data/books.parquet \
  --out /app/results --favorite-counts 1,2,3,4,5
```

**Locally with uv (from `src/evaluation/`):**

```bash
uv sync
uv run python -m evaluation.run --synthetic          # or --interactions ... --books ...
uv run pytest --cov=evaluation                       # 45 tests
```

`uv run python -m evaluation.run --help` lists every option: `--split tune` for tuning, `--models`, `--aggregations`, `--n-pairs`, `--k`, `--knn-neighbors` and `--seed`.

## Input contract (from preprocessing)

| Table | Column | Meaning |
| --- | --- | --- |
| interactions | `user_id` | Goodreads user ID |
| | `work_id` | work ID after merging editions |
| | `rating` | 0–5; 0 = shelved but unrated. A like is rating ≥ 4 |
| books | `work_id` | one row per work |
| | `genres` | list, or `\|`-separated string; used **only** to label pairs |
| | `title`, `author` | optional, for readable sample output |

CSV, Parquet or JSON Lines. Duplicate (user, work) rows keep the highest rating. If a `<file>.dvc` sits next to an input, its DVC md5 is recorded with the file's sha256 in `config.json`.

## Method

1. **User split, 80/10/10** (train / tune / test), by user, seeded. Models only ever see training users.
2. **Catalogue:** works liked by at least one training user. No model can recommend anything else.
3. **Readers:** tune or test users with ≥ 15 likes in the catalogue. Five random likes become the favorites; the rest are hidden.
4. **Pairs:** each reader's genre profile comes from their five favorites. From 20 × `n_pairs` random candidate pairs, the top quartile by profile cosine is "similar" and the bottom quartile "different"; half the pairs come from each. No model output is used.
5. **Lists:** each model scores every work per reader, scaled to [0, 1]. Scores are combined by `average`, `least_misery` (ties broken by average) or `merged_seeds` (all ten favorites as one reader). Favorites are excluded.
6. **Robustness:** `--favorite-counts 1,2,3,4,5` reruns with the first *n* favorites against the same hidden set.

## Metrics

| Metric | Definition |
| --- | --- |
| **Min-Recall@10** (primary) | min(Recall@10 for A, Recall@10 for B). Recall = hits in top 10 ÷ hidden likes |
| NDCG@10 | binary relevance, averaged over the two readers; ideal DCG uses min(hidden, 10) hits |
| Long-tail coverage | share of long-tail works recommended at least once; the head is the top 20% of works by training likes |
| Catalogue coverage | share of catalogue works recommended at least once |
| Both-Hit@10 | list contains a work hidden for both readers; only over pairs whose hidden sets overlap (`both_hit_eligible_share`) |

Means come with a 95% interval (1.96 × standard error), overall and per pair kind.

## Outputs

`<out>/<run_id>/`:

| File | Contents |
| --- | --- |
| `config.json` | arguments, git commit, data sha256/DVC md5, split sizes, counts |
| `summary.csv`, `summary.md` | metrics per model × aggregation × favorites × pair kind |
| `per_pair.csv` | one row per pair and configuration |
| `sample_recommendations.json` | three readable input → output examples, marking which reader each hit belongs to |
| `run.log` | the run's log |

A committed example run is in [docs/ms2/evaluation](../../docs/ms2/evaluation/).

## Models

`popularity` (B0) and `item_knn` (B1, cosine on the binary like matrix, top-100 neighbours) are reference implementations so the harness can be checked end to end. Any model plugs in by implementing `Recommender` in [`evaluation/models.py`](evaluation/models.py): `fit(train_interactions)`, `items`, and `score(favorites)` returning one [0, 1] score per item. That covers the team's B0–B2 baselines and the M1 hybrid.

## Tests

The tests check metrics against hand-calculated values. They also check that the split is disjoint, readers and pairs are deterministic, aggregation rules are correct, favorites are never recommended, and no evaluated reader was a training user. As a whole-harness sanity check, item-kNN must beat popularity on structured synthetic data.

## AI assistance

The first version of this package was drafted with Claude (Anthropic), then reviewed, run and tested by the committing team member.

## B2 (ALS) and the backend export

`evaluation/als.py` adds **B2, implicit ALS**, through the `Recommender` interface. It scores with the backend's rule (unit mean of seed vectors, cosine), and is part of the default `--models` (popularity, item_knn, als). `evaluation/export.py` refits B2 on all users and writes the backend's artifact folder:

```bash
python -m evaluation.export --processed /app/processed --out /app/artifacts   # compose service `train`
```

Details, hyperparameters and early results: [docs/ms2/models/README.md](../../docs/ms2/models/README.md).
