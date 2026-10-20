# Experiment logs (real Goodreads data, `data_version gr-317756d1a1ad`)

Each folder holds `run.log`, `summary.md` (all metrics) and `config.json` (arguments, data hashes, code version).

| Folder | Split | What |
|---|---|---|
| `test-first-settings-f32-r10` | test | B0, B1, B2 with the first ALS settings (32 factors, reg 10) |
| `tune-baselines` | tune | B0 and B1 reference on the tune split |
| `tune-f{factors}-r{reg}` | tune | ALS grid: factors 16–256, regularization 1–400 (18 settings) |
| `test-tuned-f128-r50` | test | Tuned B2 (128 factors, reg 50), the chosen model |

Results and the next iteration are summarized in [`../README.md`](../README.md).
