# ingest: download raw Goodreads files

Part of the TasteBridge data pipeline (`ingest → preprocess → embed / evaluation`). Owner: Cathy.

Downloads the two genre metadata files, the two genre interaction files and the author table into `data/raw/`, and writes `data/raw/manifest.json` (sha256, size and line cap for each file). Standard library only.

```bash
# from the repo root
INGEST_SAMPLE_LINES=200000 docker compose --profile pipeline run --rm ingest   # demo slice
docker compose --profile pipeline run --rm ingest                               # full files

# local tests (from this folder)
uv run pytest -q
```

Settings, the file list and the full pipeline: [docs/ms2/datapipeline/README.md](../../../docs/ms2/datapipeline/README.md).
