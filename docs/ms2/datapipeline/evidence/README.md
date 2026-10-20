# Data pipeline evidence (MS2)

| File | What it shows |
|---|---|
| `e2e-full-windows.log` | **One-command end-to-end run** on the full data (Oct 20, Windows 11 PowerShell, no `make`): `docker compose --profile pipeline run --rm pipeline` → ingest → preprocess → embed + train → evaluation, exit code 0 in ~24 min. Every stage logs `data_version gr-317756d1a1ad`; each stage's own container log is appended at the end |
| `e2e-full-windows-results/` | `summary.md` and `config.json` of that run's evaluation (Min-Recall@10: popularity 0.038, item-kNN 0.071, ALS 0.043 average / 0.024 least misery, matching [models](../../models/)) |
| `real-ingest-manifest.json` | Full Goodreads download: source URLs, bytes and sha256 of all 5 files |
| `real-preprocess-manifest.json` | Full preprocess run: parameters, counts (80,197,446 lines → 499,915 interactions, 9,896 readers, 5,000 works), quality summary, `data_version gr-317756d1a1ad` |
| `sample-input.json` | Small **synthetic** input: first raw interaction and book lines (`make demo`) |
| `sample-output.json` | The same synthetic data after preprocess: rows of `interactions.parquet` and `books.parquet`, counts, `data_version` |
| `demo.log` | Console log of `make demo` (synthetic data → preprocess → evaluation) |
| `train.log`, `export-meta.json` | `make train` on the real data: tuned B2 (128 factors, reg 50) exported for the API |

Real Goodreads rows are not committed (academic use only, no redistribution); the sample input/output uses invented Goodreads-shaped data. The real data is versioned with DVC (`data/*.dvc`).
