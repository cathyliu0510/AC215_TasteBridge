# TasteBridge one-command entry points. Run from the repo root.
#
#   make pipeline   full data:  ingest -> preprocess -> embed -> evaluation
#   make sample     fast demo:  same, first SAMPLE_LINES lines of each interaction file
#   make data       ingest + preprocess only (no 3 GB embed image)
#   make demo       fully offline: invented Goodreads-shaped data -> preprocess -> evaluation
#   make evaluate   evaluation (B0, B1, B2) on whatever is in data/processed
#   make train      train B2 ALS on data/processed and export data/artifacts/current
#   make serve      backend API serving the trained model (http://localhost:9000/docs)
#   make app        frontend + backend with the trained model (http://localhost:4176)
#   make test       unit tests of the pipeline stages (needs uv)
#   make dvc-push   version data/ with DVC and upload it to gs://tastebridge-dvc

SAMPLE_LINES ?= 200000
# folder under data/ that evaluation reads
EVAL_DATA ?= processed
RUN_ID ?= $(shell date +%Y%m%d-%H%M%S)
COMPOSE = docker compose --profile pipeline
GIT_COMMIT := $(shell git rev-parse HEAD 2>/dev/null)
export GIT_COMMIT

.PHONY: pipeline sample data demo evaluate train serve app test dvc-push clean-processed

pipeline:
	$(COMPOSE) build
	INGEST_SAMPLE_LINES=0 $(COMPOSE) run --rm embed      # depends_on runs ingest + preprocess first
	$(MAKE) train evaluate

sample:
	$(COMPOSE) build
	INGEST_SAMPLE_LINES=$(SAMPLE_LINES) $(COMPOSE) run --rm embed
	$(MAKE) train evaluate

data:
	INGEST_SAMPLE_LINES=$${INGEST_SAMPLE_LINES:-$(SAMPLE_LINES)} $(COMPOSE) run --rm --build preprocess

# Demo data lives in data/synthetic/ so it can never overwrite real downloads in data/raw.
demo:
	$(COMPOSE) build preprocess
	$(COMPOSE) run --rm --no-deps preprocess python synthetic_raw.py --out /data/synthetic/raw --works 600 --users 3000
	$(COMPOSE) run --rm --no-deps -e RAW_DIR=/data/synthetic/raw -e PROCESSED_DIR=/data/synthetic/processed preprocess
	$(MAKE) evaluate EVAL_DATA=synthetic/processed RUN_ID=synthetic-$(RUN_ID)

evaluate:
	mkdir -p src/evaluation/results
	EVAL_DATA=$(EVAL_DATA) docker compose --profile evaluation run --rm --build evaluation \
		--interactions /app/processed/interactions.parquet \
		--books /app/processed/books.parquet \
		--out /app/results --favorite-counts 1,2,3,4,5 --run-id $(RUN_ID)

train:
	mkdir -p data/artifacts
	$(COMPOSE) run --rm --no-deps --build train

serve:
	ARTIFACT_DIR=/artifacts/current docker compose up --build backend

app:
	ARTIFACT_DIR=/artifacts/current docker compose -f compose.integration.yml up --build

test:
	cd src/datapipeline/ingest && uv run pytest -q
	cd src/datapipeline/preprocess && uv run pytest -q
	cd src/evaluation && uv run pytest -q

dvc-push:
	dvc add data/raw data/processed
	@if [ -d data/embeddings ]; then dvc add data/embeddings; fi
	@if [ -d data/artifacts ]; then dvc add data/artifacts; fi
	dvc push
	@echo "Now commit the .dvc pointer files:  git add data/*.dvc && git commit"

clean-processed:
	rm -rf data/processed data/processed.tmp data/processed.old
