import json

from embed.query import format_examples_md, main, run_examples, write_examples
from embed.store import build_collection, chroma_metadata, release_chroma, write_meta
from embed.texts import build_texts


def _build(out_dir, encoder, books_df):
    texts, sources = build_texts(books_df)
    emb = encoder.encode(texts)
    metas = [
        chroma_metadata(t, a, g, y, s)
        for t, a, g, y, s in zip(
            books_df["title"], books_df["author"], books_df["genre"], books_df["year"], sources
        )
    ]
    collection = build_collection(out_dir / "chroma", books_df["work_id"].tolist(), emb, texts, metas)
    return collection, texts


def test_run_examples_and_write(tmp_path, encoder, books_df):
    collection, texts = _build(tmp_path, encoder, books_df)
    examples = run_examples(collection, encoder, [texts[0]], k=3)
    first = examples[0]["results"][0]
    assert examples[0]["query"] == texts[0]
    assert first["work_id"] == "syn-001"
    assert "document" not in first and "excerpt" not in first
    write_examples(tmp_path, examples)
    assert json.loads((tmp_path / "retrieval_example.json").read_text(encoding="utf-8")) == examples
    md = (tmp_path / "retrieval_example.md").read_text(encoding="utf-8")
    assert "| Query | Rank | Title |" in md and "The Glass Heist" in md
    release_chroma()


def test_run_examples_excerpts(tmp_path, encoder, books_df):
    collection, texts = _build(tmp_path, encoder, books_df)
    examples = run_examples(collection, encoder, [texts[0]], k=2, excerpts=True)
    assert all(len(r["excerpt"]) <= 200 for r in examples[0]["results"])
    release_chroma()


def test_md_escapes_pipes():
    md = format_examples_md(
        [{"query": "a|b", "results": [{"rank": 1, "work_id": "w", "title": "X|Y", "author": None,
                                         "genre": None, "similarity": 0.5, "text_source": "description"}]}]
    )
    assert "a\\|b" in md and "X\\|Y" in md


def test_cli_main_uses_meta_model(tmp_path, encoder, books_df, capsys):
    out = tmp_path / "embeddings"
    out.mkdir()
    _, texts = _build(out, encoder, books_df)
    write_meta(out, {"embedding_model": "test/hash-encoder", "model_revision": "test"})
    release_chroma()
    calls = []

    def factory(name, revision):
        calls.append((name, revision))
        return encoder

    code = main([texts[0], "--dir", str(out), "--k", "2"], encoder_factory=factory)
    assert code == 0
    assert calls == [("test/hash-encoder", "test")]
    assert "The Glass Heist" in capsys.readouterr().out
    release_chroma()


def test_cli_main_missing_index(tmp_path, capsys):
    assert main(["anything", "--dir", str(tmp_path / "none")]) == 1
    assert "embed.run" in capsys.readouterr().err


def test_cli_main_index_folder_without_collection(tmp_path, capsys):
    out = tmp_path / "embeddings"
    (out / "chroma").mkdir(parents=True)
    write_meta(out, {"embedding_model": "m", "model_revision": "r"})
    assert main(["anything", "--dir", str(out)]) == 1
    assert "embed.run" in capsys.readouterr().err
    release_chroma()


def test_cli_main_meta_missing_keys(tmp_path, encoder, books_df, capsys):
    out = tmp_path / "embeddings"
    out.mkdir()
    _build(out, encoder, books_df)
    write_meta(out, {"stage": "embed"})
    release_chroma()
    assert main(["anything", "--dir", str(out)], encoder_factory=lambda n, r: encoder) == 1
    assert "meta.json" in capsys.readouterr().err
    release_chroma()
