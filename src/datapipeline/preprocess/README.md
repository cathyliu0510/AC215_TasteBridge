# preprocess: raw files → work-level catalogue + interactions

Part of the TasteBridge data pipeline. Owners: Cathy (`preprocess.py`), YiTong (`quality.py`).

Reads `data/raw/` and writes three files to `data/processed/`:
- `books.parquet`: one row per work (≤ 5,000)
- `interactions.parquet`: one row per (user, work), ≤ 500,000
- `manifest.json`: with the `data_version`

Steps, output contract and settings: [docs/ms2/datapipeline/README.md](../../../docs/ms2/datapipeline/README.md).

```bash
# from the repo root
docker compose --profile pipeline run --rm --no-deps preprocess     # on existing data/raw

# fully offline demo data (invented, Goodreads-shaped)
docker compose --profile pipeline run --rm --no-deps preprocess python synthetic_raw.py --out /data/raw

# local tests (from this folder)
uv run pytest -q          # 121 tests: preprocess + quality
```
