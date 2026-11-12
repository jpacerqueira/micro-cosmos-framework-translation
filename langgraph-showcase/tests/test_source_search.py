"""Tests for the context-window-overflow fix in the TDD writer loop:

  - list_source_files() actually filtering by seam_name (micro_cosmos/tools/source_tools.py)
  - chunk_source_file()'s IR-node-boundary chunking (micro_cosmos/retrieval/source_chunks.py)
  - search_relevant_source()'s lexical-mode search (micro_cosmos/tools/source_search_tools.py)

All exercised without an LLM/embedding server — skip_llm=True forces the lexical
(Jaccard token-overlap) fallback in RunIndex.search(), matching this session's
existing deterministic-mode-friendly testing pattern.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def skip_llm_settings(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    return s


@pytest.fixture
def small_source_tree(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text(
        "def calculate_interest(balance, rate):\n"
        "    return balance * rate / 100\n"
        "\n\n"
        "def validate_amount(amount):\n"
        "    if amount < 0:\n"
        "        raise ValueError('negative amount')\n"
        "    return amount\n",
        encoding="utf-8",
    )
    (src / "bar.py").write_text("def unrelated_thing():\n    return 42\n", encoding="utf-8")
    return src


@pytest.fixture
def run_dir_with_seam(tmp_path, small_source_tree):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    seam_data = {
        "seams": [
            {
                "id": "seam_object_foo",
                "type": "object",
                "location": "prog.Foo",
                "source_location": f"{small_source_tree / 'foo.py'}:1",
                "evidence": ["fan-in: 3"],
            }
        ]
    }
    (run_dir / "seam.json").write_text(json.dumps(seam_data), encoding="utf-8")
    return run_dir


def test_list_source_files_scopes_to_seam(small_source_tree, run_dir_with_seam):
    from micro_cosmos.tools.source_tools import list_source_files, set_run_dir

    set_run_dir(str(run_dir_with_seam))
    result = list_source_files(str(small_source_tree), "python3", seam_name="seam_object_foo")

    assert result["scope"] == "seam"
    assert result["count"] == 1
    assert result["files"][0]["relative_path"] == "foo.py"


def test_list_source_files_falls_back_when_seam_unresolvable(small_source_tree, run_dir_with_seam):
    from micro_cosmos.tools.source_tools import list_source_files, set_run_dir

    set_run_dir(str(run_dir_with_seam))
    result = list_source_files(str(small_source_tree), "python3", seam_name="seam_does_not_exist")

    assert result["scope"] == "estate-wide"
    assert result["count"] == 2


def test_list_source_files_unfiltered_without_seam_name(small_source_tree, run_dir_with_seam):
    from micro_cosmos.tools.source_tools import list_source_files, set_run_dir

    set_run_dir(str(run_dir_with_seam))
    result = list_source_files(str(small_source_tree), "python3")

    assert result["scope"] == "estate-wide"
    assert result["count"] == 2


def test_chunk_source_file_splits_on_ir_node_boundaries(small_source_tree):
    from micro_cosmos.retrieval.source_chunks import chunk_source_file

    foo = small_source_tree / "foo.py"
    nodes = [
        {"id": "n1", "name": "calculate_interest", "source_location": f"{foo}:1"},
        {"id": "n2", "name": "validate_amount", "source_location": f"{foo}:5"},
    ]
    chunks = chunk_source_file(foo, small_source_tree, nodes)

    assert len(chunks) == 2
    assert "calculate_interest" in chunks[0].text
    assert "validate_amount" not in chunks[0].text
    assert "validate_amount" in chunks[1].text
    assert chunks[0].source_location == f"{foo}:1"
    assert chunks[1].source_location == f"{foo}:5"


def test_chunk_source_file_falls_back_to_sliding_window_with_no_nodes(small_source_tree):
    from micro_cosmos.retrieval.source_chunks import chunk_source_file

    bar = small_source_tree / "bar.py"
    chunks = chunk_source_file(bar, small_source_tree, [])

    assert len(chunks) >= 1
    assert "unrelated_thing" in chunks[0].text


def test_search_relevant_source_lexical_mode(skip_llm_settings, small_source_tree, run_dir_with_seam):
    from micro_cosmos.tools.source_search_tools import search_relevant_source

    result = search_relevant_source(
        seam_name="seam_object_foo",
        query="calculate interest balance rate",
        source_path=str(small_source_tree),
        source_lang="python3",
        run_dir=str(run_dir_with_seam),
        k=5,
    )

    assert result["mode"] == "lexical"
    assert result["scope"] == "seam"
    assert result["results"], "expected at least one lexical search result"
    assert any("calculate_interest" in r["text"] for r in result["results"])
    # Never a full, uncapped file — the whole point of this tool over read_source_file.
    assert all(len(r["text"]) < 5_000 for r in result["results"])


def test_search_in_source_accepts_string_limits(tmp_path):
    """Confirmed live: max_results arrived as a string and
    ``len(results) >= max_results`` raised ``'>=' not supported between
    instances of 'int' and 'str'``."""
    from micro_cosmos.tools.security_tools import search_in_source

    (tmp_path / "A.java").write_text("class A {\n  void fraudScore() {}\n}\n", encoding="utf-8")
    (tmp_path / "B.java").write_text("class B {\n  void fraudScore() {}\n}\n", encoding="utf-8")
    result = search_in_source(
        str(tmp_path),
        "fraudScore",
        max_results="1",
        context_lines="0",
        file_extensions='["java"]',
    )
    assert result["total_matches"] == 1
    assert "error" not in result


def test_search_relevant_source_accepts_string_k():
    """Confirmed live: k arrived as a string and ``min(k, 10)`` raised
    ``'<' not supported between instances of 'str' and 'int'``."""
    from micro_cosmos.tools.source_search_tools import search_relevant_source

    result = search_relevant_source(query="q", source_path="", run_dir="", k="7")
    assert result["results"] == []
    assert result["mode"] == "none"


def test_search_relevant_source_string_k_is_honored(skip_llm_settings, small_source_tree, run_dir_with_seam):
    from micro_cosmos.tools.source_search_tools import search_relevant_source

    result = search_relevant_source(
        seam_name="seam_object_foo",
        query="calculate interest balance rate",
        source_path=str(small_source_tree),
        source_lang="python3",
        run_dir=str(run_dir_with_seam),
        k="2",
    )
    assert result["results"]
    assert len(result["results"]) <= 2


def test_search_relevant_source_requires_run_dir_and_source_path():
    from micro_cosmos.tools.source_search_tools import search_relevant_source

    result = search_relevant_source(
        seam_name="x", query="q", source_path="", source_lang="python3", run_dir="",
    )
    assert result["results"] == []
    assert result["mode"] == "none"


def test_seam_relevant_files_ignores_non_directory_side_a_side_b(tmp_path):
    """side_a/side_b mean prose ("3 caller(s)") for most seam types, and
    bounded-context/task labels (not real paths) for context/scheduler link
    seams — only a directory-based link seam's side_a/side_b are real
    top-level directories. None of the non-directory cases should match any
    file."""
    from micro_cosmos.tools.source_tools import _seam_relevant_files

    root = tmp_path / "src"
    root.mkdir()
    (root / "Foo.java").write_text("class Foo {}", encoding="utf-8")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    seam_data = {
        "seams": [
            {
                "id": "seam_context_A__B",
                "type": "link",
                "location": "A ↔ B",
                "source_location": "",
                "side_a": "A",  # a bounded-context name, not a directory
                "side_b": "B",
            }
        ]
    }
    (run_dir / "seam.json").write_text(json.dumps(seam_data), encoding="utf-8")

    result = _seam_relevant_files(root, str(run_dir), "seam_context_A__B")
    assert result is None


def test_seam_relevant_files_directory_link_seam_does_not_cross_boundary(tmp_path):
    """A directory-based link seam's side_a="Payment/" must match files under
    Payment/ only — not a sibling "PaymentGateway/" directory that happens to
    share the same string prefix."""
    from micro_cosmos.tools.source_tools import _seam_relevant_files

    root = tmp_path / "src"
    (root / "Payment").mkdir(parents=True)
    (root / "Payment" / "Invoice.java").write_text("class Invoice {}", encoding="utf-8")
    (root / "PaymentGateway").mkdir(parents=True)
    (root / "PaymentGateway" / "Gateway.java").write_text("class Gateway {}", encoding="utf-8")
    (root / "Billing").mkdir(parents=True)
    (root / "Billing" / "Invoice.java").write_text("class Invoice {}", encoding="utf-8")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    seam_data = {
        "seams": [
            {
                "id": "seam_link_Payment__Billing",
                "type": "link",
                "location": "Payment/ ↔ Billing/",
                "source_location": "",
                "side_a": "Payment/",
                "side_b": "Billing/",
            }
        ]
    }
    (run_dir / "seam.json").write_text(json.dumps(seam_data), encoding="utf-8")

    result = _seam_relevant_files(root, str(run_dir), "seam_link_Payment__Billing")
    assert result is not None
    relative = {str(p.relative_to(root)) for p in result}
    assert relative == {"Payment/Invoice.java", "Billing/Invoice.java"}


def test_load_source_index_is_cached_in_memory(monkeypatch, small_source_tree, run_dir_with_seam):
    """search_relevant_source() is called repeatedly across every seam/iteration
    in a run — load_source_index() must not re-read chunks.jsonl/embeddings.npy
    from disk on every call, undercutting the whole point of building the index
    once (real finding from code review)."""
    import micro_cosmos.retrieval.source_index as si

    si._INDEX_CACHE.clear()
    calls = {"count": 0}
    original = si.load_from_sidecar

    def _spy(vdir):
        calls["count"] += 1
        return original(vdir)

    monkeypatch.setattr(si, "load_from_sidecar", _spy)

    idx1 = si.load_source_index(run_dir_with_seam, str(small_source_tree), "python3", {})
    idx2 = si.load_source_index(run_dir_with_seam, str(small_source_tree), "python3", {})

    assert idx1 is idx2
    assert calls["count"] == 1, "load_from_sidecar should only be hit once; the second call must be served from the in-memory cache"
