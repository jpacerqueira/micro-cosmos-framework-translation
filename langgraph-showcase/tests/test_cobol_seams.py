"""Regression tests for COBOL seam detection.

Covers three bugs found while investigating why seam detection produced
zero object/boundary seams for a real COBOL estate (examples/cobol-
bankxyz_fraud_detection):

1. observer_tools.py's COBOL parser silently dropped PERFORM calls issued
   from a program's "mainline" body — the common COBOL pattern of real
   logic running directly under PROCEDURE DIVISION, before any named
   paragraph header. No PROCEDURE node existed to attribute those calls
   to, so the edges were never created at all.
2. seam_tools.py's _detect_seams() only ever examined PROGRAM-type nodes,
   never PROCEDURE-type nodes — so even the CALLS edges that did survive
   (paragraph-to-paragraph PERFORMs) were invisible to seam detection,
   which is where COBOL's real internal structure lives (COBOL has no
   classes; a single PROGRAM's substance is its paragraphs).
3. The PROGRAM-level fan-in threshold (3) was tuned for Java-scale
   codebases and excluded this estate's two real hub programs (FDRULES,
   FDALERT), which top out at 2 callers each.
"""

from __future__ import annotations

from micro_cosmos.tools.observer_tools import parse_source_estate
from micro_cosmos.tools.seam_tools import identify_seams

ESTATE = "examples/cobol-bankxyz_fraud_detection"


def test_cobol_parser_attributes_mainline_perform_calls() -> None:
    """A PROCEDURE node for the implicit mainline body must exist, and at
    least one CALLS edge must originate from it — proving PERFORM calls
    issued before the first named paragraph are no longer silently dropped.
    """
    ir = parse_source_estate(ESTATE, "cobol")
    mainline_ids = {
        n["id"] for n in ir["nodes"]
        if n.get("type") == "PROCEDURE" and n["id"].endswith(".mainline")
    }
    assert mainline_ids, "expected at least one synthesized mainline PROCEDURE node"

    proc_calls_from_mainline = [
        e for e in ir["edges"]
        if e.get("type") == "CALLS" and e["source_id"] in mainline_ids
    ]
    assert proc_calls_from_mainline, (
        "expected at least one CALLS edge attributed to a mainline node — "
        "PERFORM statements issued before the first paragraph header must "
        "not be silently dropped"
    )


def test_cobol_seam_detection_finds_real_program_hubs() -> None:
    """FDRULES and FDALERT are this estate's two real cross-program hubs
    (each called by 2 other programs) — below the fixed fan-in threshold
    of 3, but the biggest hubs that actually exist in this estate. The
    adaptive threshold must surface them anyway.
    """
    seams = identify_seams(ESTATE, "cobol")
    object_or_boundary_locations = {
        s["location"] for s in seams["seams"] if s["type"] in ("object", "boundary")
    }
    assert "prog.FDRULES" in object_or_boundary_locations
    assert "prog.FDALERT" in object_or_boundary_locations


def test_cobol_seam_detection_finds_procedure_level_hubs() -> None:
    """A paragraph called from multiple places within the same program
    (proc.FDALERT.return-to-caller) must also surface as a seam — this
    signal did not exist at all before the PROCEDURE-level fan-in pass was
    added, since _detect_seams() previously only examined PROGRAM nodes.
    """
    seams = identify_seams(ESTATE, "cobol")
    procedure_seam_locations = {
        s["location"] for s in seams["seams"]
        if s["type"] in ("object", "boundary") and s["location"].startswith("proc.")
    }
    assert procedure_seam_locations, (
        "expected at least one PROCEDURE-level object/boundary seam"
    )
