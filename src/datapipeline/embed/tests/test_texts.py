import numpy as np
import pandas as pd

from embed.texts import as_list, build_text, build_texts, fallback_has_description


def test_build_text_with_description():
    assert build_text("The Glass Heist", "Mara Quill", "A crew plans a robbery.", ["heist"], True) == (
        "The Glass Heist by Mara Quill. A crew plans a robbery.",
        "description",
    )


def test_build_text_fallback_uses_first_8_shelves():
    text, source = build_text("T", "A", None, [f"s{i}" for i in range(10)], False)
    assert source == "title_shelves"
    assert text == "T by A. Shelves: s0, s1, s2, s3, s4, s5, s6, s7"


def test_build_text_no_shelves():
    assert build_text("T", "A", None, [], False) == ("T by A.", "title_shelves")


def test_build_text_flag_true_but_description_missing_falls_back():
    assert build_text("T", "A", pd.NA, ["heist"], True) == ("T by A. Shelves: heist", "title_shelves")
    assert build_text("T", "A", None, None, True) == ("T by A.", "title_shelves")
    assert build_text("T", "A", "   ", None, True) == ("T by A.", "title_shelves")


def test_build_text_missing_author():
    assert build_text("T", None, None, [], False) == ("T.", "title_shelves")
    assert build_text("T", pd.NA, None, [], False) == ("T.", "title_shelves")


def test_as_list_handles_parquet_types():
    assert as_list(np.array(["a", "b"], dtype=object)) == ["a", "b"]
    assert as_list(None) == []
    assert as_list(float("nan")) == []
    assert as_list(pd.NA) == []
    assert as_list("solo") == ["solo"]
    assert as_list(["a", None, "b"]) == ["a", "b"]


def test_build_texts_uses_has_description_column(books_df):
    texts, sources = build_texts(books_df)
    assert len(texts) == len(books_df)
    assert sources == ["description" if f else "title_shelves" for f in books_df["has_description"]]
    assert texts[0].startswith("The Glass Heist by Mara Quill. A crew of con artists")


def test_build_texts_falls_back_to_local_rule_without_column(books_df):
    raw = books_df.drop(columns=["has_description", "description_issue"]).copy()
    raw["description"] = raw["description"].astype(object)
    raw.loc[0, "description"] = "<p>" + raw.loc[0, "description"] + "</p>"
    texts, sources = build_texts(raw)
    assert sources == [
        "description" if fallback_has_description(d) else "title_shelves" for d in raw["description"]
    ]
    assert "<p>" not in texts[0]


def test_build_texts_after_parquet_round_trip(books_path):
    texts, _ = build_texts(pd.read_parquet(books_path))
    assert all("<NA>" not in t and "None" not in t and "nan" not in t for t in texts)
