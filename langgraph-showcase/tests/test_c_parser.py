"""Tests for C source support (Observer's tree-sitter deep parser + call
extractor for the "c" source language, plus two real bugs this exposed:

- _extensions_for did fuzzy-only matching, so source_lang="c" silently
  resolved to COBOL's extensions ("cobol".startswith("c") is True, and
  cobol was registered earlier in the dict) — invisible until "c" existed
  as a source language at all.
- .c/.h pairs sharing a base name (the near-universal C convention)
  collided into two PROGRAM nodes with the identical generated id.
"""

from __future__ import annotations

import pytest

from micro_cosmos.tools.observer_tools import (
    _C_TS_AVAILABLE,
    _extensions_for,
    _extract_calls_c,
    _parse_c_ts_file,
    observe_source_estate,
)

pytestmark = pytest.mark.skipif(not _C_TS_AVAILABLE, reason="tree-sitter-c not installed")


# ── _extensions_for regression ──────────────────────────────────────────────

def test_extensions_for_c_is_not_cobols_extensions():
    assert _extensions_for("c") == [".c", ".h"]
    assert _extensions_for("cobol") == [".cbl", ".cob", ".cobol"]


# ── _parse_c_ts_file ─────────────────────────────────────────────────────────

_SAMPLE = '''
#include "helper.h"
#include <stdio.h>

struct Account {
    char id[10];
    int balance;
};

static int validate(int amount) {
    return amount > 0 ? 1 : 0;
}

int compute_score(struct Account *acct, int amount) {
    int base = amount * 2;
    if (validate(base)) {
        return base + acct->balance;
    }
    return 0;
}
'''


def test_parses_struct_with_fields():
    nodes, _edges = _parse_c_ts_file("account.c", _SAMPLE, "prog.Account")
    struct_nodes = [n for n in nodes if n.id == "struct.Account"]
    assert len(struct_nodes) == 1
    field_ids = {n.id for n in nodes if n.type.value == "DATA_ITEM"}
    assert field_ids == {"field.Account.id", "field.Account.balance"}


def test_struct_specifier_used_only_as_a_type_reference_is_not_a_definition():
    """`struct Account *acct` in a parameter list must not itself produce a
    second, spurious struct.Account definition node."""
    nodes, _edges = _parse_c_ts_file("account.c", _SAMPLE, "prog.Account")
    struct_nodes = [n for n in nodes if n.type.value == "DATA_STRUCTURE"]
    assert len(struct_nodes) == 1


def test_parses_functions_with_params_return_type_and_storage():
    nodes, _edges = _parse_c_ts_file("account.c", _SAMPLE, "prog.Account")
    by_id = {n.id: n for n in nodes}

    validate = by_id["fn.validate"]
    assert validate.inputs == [{"name": "amount", "type": "int"}]
    assert validate.output == "int"
    assert validate.attributes["storage"] == "static"

    compute = by_id["fn.compute_score"]
    assert compute.inputs == [
        {"name": "acct", "type": "struct Account"},
        {"name": "amount", "type": "int"},
    ]
    assert compute.attributes["storage"] == ""


def test_no_args_void_idiom_produces_empty_inputs_not_a_void_parameter():
    nodes, _edges = _parse_c_ts_file("m.c", "int main(void) { return 0; }", "prog.m")
    main_fn = next(n for n in nodes if n.id == "fn.main")
    assert main_fn.inputs == []


def test_real_intra_file_call_graph():
    _nodes, edges = _parse_c_ts_file("account.c", _SAMPLE, "prog.Account")
    calls = {(e.source_id, e.target_id) for e in edges if e.type.value == "CALLS"}
    assert ("fn.compute_score", "fn.validate") in calls


def test_function_prototype_without_a_body_is_not_a_definition():
    content = "extern void log_message(const char *msg);\nint add(int a, int b) { return a + b; }"
    nodes, _edges = _parse_c_ts_file("u.c", content, "prog.u")
    ids = {n.id for n in nodes}
    assert "fn.log_message" not in ids
    assert "fn.add" in ids


def test_duplicate_function_names_get_disambiguated():
    content = "int add(int a, int b) { return a + b; }\nint add(int a, int b, int c) { return a + b + c; }"
    nodes, _edges = _parse_c_ts_file("u.c", content, "prog.u")
    fn_ids = [n.id for n in nodes if n.id.startswith("fn.add")]
    assert len(fn_ids) == 2
    assert len(set(fn_ids)) == 2


def test_pointer_returning_function_name_resolves_correctly():
    nodes, _edges = _parse_c_ts_file(
        "u.c", 'char *get_name(int id) { return "x"; }', "prog.u",
    )
    assert any(n.id == "fn.get_name" for n in nodes)


# ── _extract_calls_c ─────────────────────────────────────────────────────────

def test_local_include_produces_an_edge_system_include_does_not():
    edges = _extract_calls_c(_SAMPLE, "prog.Account")
    targets = {t for _s, t in edges}
    assert "prog.Helper_h" in targets
    assert not any("stdio" in t.lower() for t in targets)


def test_header_include_targets_the_headers_own_h_suffixed_id():
    edges = _extract_calls_c('#include "account.h"\n', "prog.Impl")
    assert edges == [("prog.Impl", "prog.Account_h")]


# ── full estate integration ─────────────────────────────────────────────────

def test_header_and_implementation_sharing_a_stem_do_not_collide(tmp_path):
    """The near-universal C convention (account.c + account.h) must not
    produce two PROGRAM nodes with the identical generated id."""
    (tmp_path / "account.h").write_text(
        "struct Account {\n    int balance;\n};\n"
    )
    (tmp_path / "account.c").write_text(
        '#include "account.h"\n'
        "int get_balance(struct Account *a) { return a->balance; }\n"
    )

    result = observe_source_estate(str(tmp_path), "c")
    program_ids = [n["id"] for n in result["nodes"] if n["type"] == "PROGRAM"]
    assert len(program_ids) == len(set(program_ids)), "duplicate PROGRAM node ids"
    assert "prog.Account" in program_ids
    assert "prog.Account_h" in program_ids

    struct_defines = [
        e for e in result["edges"]
        if e["type"] == "DEFINES" and e["target_id"] == "struct.Account"
    ]
    assert len(struct_defines) == 1
    assert struct_defines[0]["source_id"] == "prog.Account_h"
