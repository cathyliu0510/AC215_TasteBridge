# MS2 baseline models: B0, B1, B2

Owners: **Cathy** (B2 ALS, tuning, artifact export), **Anhad** (evaluation harness, B0, B1). Code: [`src/evaluation/evaluation/`](../../../src/evaluation/evaluation/).

## What each model does

| ID | Model | File | Idea | Served by the app? |
|---|---|---|---|---|
| **B0** | Popularity | `models.py` | Rank works by number of likes in training; ignores the readers | No (offline floor) |
| **B1** | Item-kNN | `models.py` | Cosine similarity between works on the user × work like matrix; score = summed similarity to the favorites (top 100 neighbours each) | No (offline) |
| **B2** | Implicit ALS | `als.py` | One vector per reader and per work (Hu, Koren & Volinsky 2008); score = cosine between each work and the reader's taste vector | **Yes**: `export.py` writes the backend's artifact folder |

**Why B2 is the one served.** The backend (`src/backend/app/recommender.py`, SPEC §5) ranks with *one vector per book*:
1. Each reader's taste vector is the mean of their favorites' vectors, scaled to length 1.
2. Every book gets a cosine score against each taste vector.
3. The two scores are combined with least-misery or average.

ALS produces exactly those vectors. B0 has no vectors, and B1 has none of a fixed size. `ALS.score()` implements the backend's rule, so the offline numbers describe the lists users actually see.

## Pipeline: train → export → serve

```
data/processed/ ──► make train ──► data/artifacts/b2-als-<data_version>/ ──► make serve / make app
(preprocess)        (ALS on all       books.json, item_embeddings.npy,        backend loads
                     users)            coords_2d.npy (UMAP), meta.json         data/artifacts/current
```

- **Evaluation** (`make evaluate`) fits every model on **training users only** (80/10/10 user split, seed 42) and scores held-out readers in simulated pairs.
- **Export** (`make train`) refits B2 on **all** users with the same hyperparameters.
- **`coords_2d.npy`:** a 2-D UMAP of the item vectors, scaled to [-1, 1]; this is the taste galaxy.

## Data used

Full UCSD Goodreads fantasy + mystery subsets, **`data_version gr-317756d1a1ad`**:

| Step | Count |
|---|---|
| Raw interaction lines read | 80,197,446 |
| Editions → works | 470,776 → 208,416 |
| Catalogue (most liked works) | 5,000 |
| Users touching the catalogue | 709,000 (26.5M rows) |
| After ≥5 likes + 500k cap (whole users, seed 42) | **499,915 interactions** (349,962 likes), **9,896 users** |
| User split train / tune / test | 7,917 / 990 / 989 |
| Test readers with ≥15 likes | 628 → 300 pairs (150 similar-taste, 150 different-taste) |

## Hyperparameter tuning (B2, tune split only)

Every setting was scored on the **tune** split (average aggregation, 5 favorites, Min-Recall@10). The test split was not used to choose.

| factors \ regularization | 1 | 10 | 50 | 150 | 400 |
|---|---|---|---|---|---|
| 16 | 0.022 | 0.024 | 0.021 | | |
| 32 | 0.023 | 0.027 | 0.026 | | |
| 64 | 0.029 | 0.035 | 0.038 | 0.028 | 0.007 |
| 128 | | | **0.042** | 0.033 | 0.007 |
| 256 | | | 0.043 | 0.034 | 0.007 |

Reference on the same tune split: **B0 popularity 0.038**, **B1 item-kNN 0.067**.

**Chosen:** `factors = 128, regularization = 50` (new default in `als.py`).
- Recall rises with more factors, but 128 ≈ 256 (0.042 vs 0.043) at a third of the training time.
- Regularization peaks near 50. Above that, the model collapses: 0.007 at 400.

| Parameter | Value | Meaning |
|---|---|---|
| `factors` | **128** | length of each vector |
| `regularization` | **50** | shrinks vectors; protects works with few likes |
| `alpha` | 20 | extra confidence on liked (user, work) pairs |
| `iterations` | 15 | alternating solves (readers, then works) |
| `seed` | 42 | same data → same model |

Each run records these:
- in the evaluation's `results/<run>/config.json` (`arguments.als_*`)
- in the artifact's `meta.json` (`hyperparameters`)

Override them with `--als-factors`, `--als-reg`, `--als-alpha`, `--als-iterations`.

## Results on the test split

Five favorites per reader, k = 10, 300 test pairs:

| Model | Aggregation | Min-Recall@10 | NDCG@10 | Long-tail coverage |
|---|---|---|---|---|
| B0 popularity | any | 0.038 | 0.336 | 0.000 |
| **B1 item-kNN** | **average** | **0.071** | 0.404 | 0.082 |
| B1 item-kNN | least misery | 0.042 | 0.293 | 0.057 |
| B1 item-kNN | merged seeds | 0.049 | **0.413** | 0.078 |
| B2 ALS (first defaults: 32 factors, reg 10) | average | 0.033 | 0.254 | 0.157 |
| B2 ALS (first defaults) | least misery | 0.020 | 0.132 | 0.176 |
| B2 ALS (**tuned**: 128 factors, reg 50) | average | 0.043 (verified by YiTong on the same data) | | |

## What we learned

1. **Personalization works on real data.** Item-kNN roughly doubles popularity on Min-Recall@10 (0.071 vs 0.038).
2. **Tuning ALS helped a lot,** from 0.027 to 0.042 on the tune split (+56%). The tuned model now beats popularity but is still well below item-kNN.
3. **Why ALS lags: the serving rule.** The backend normalizes every book vector to length 1 and ranks by cosine. That throws away the vector length, which in ALS largely encodes how popular a book is. Popularity alone scores 0.038, so B2 loses a strong signal. The very high regularization the tuning picked fits this explanation: it shrinks noisy vectors of rarely liked books, the part popularity would otherwise correct.
4. **Least misery has a real cost.** For every model it lowers Min-Recall@10 (item-kNN 0.071 → 0.042), but it recommends more long-tail books. "Protect the less-satisfied reader" is not free on this data. The API's default aggregation (`least_misery`) should be revisited.
5. **More favorites help** (robustness runs, 1–5 favorites; see `summary.csv`). This supports asking each reader for five books.
6. **Speed:** preprocess on 80M lines takes ~6 min. Training B2 (128 factors) takes ~10–20 s. `/recommend` answers in ~6 ms, well under the proposal's 0.5 s target.

## Next iteration (MS3)

1. **Serving-rule decision with Nikhil:**
   - (a) add a popularity term to the scoring (e.g. `cosine + β·log(popularity)`, with β tuned on the tune split), or
   - (b) export item-kNN neighbours so the API can serve B1, or
   - (c) serve un-normalized ALS dot products.
   
   Each option is one extra field in the artifact format; we choose using the tune split.
2. **Default aggregation:** compare least misery and average per pair type (similar vs. different taste) before fixing the API default.
3. **Hybrid M1:** add YiTong's description embeddings (`data/embeddings/desc_embeddings.npy`, MiniLM 384-d) and shelf features to the ALS work vectors. This targets works with few likes, the weakness ALS shows above. Export in the same artifact format.
4. **More data:** raise `PREPROCESS_MAX_INTERACTIONS` from 500k (MVP cap) to 2–5M. The full catalogue has 26.5M rows, so this is cheap.
5. **Tracking:** log runs to Weights & Biases and run training as a Vertex AI job (proposal MS3).
