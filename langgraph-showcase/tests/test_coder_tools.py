"""submit_seam_translation's submission-quality checks (micro_cosmos/tools/coder_tools.py).

Confirmed live, 2026-08-24: a real Code Writer turn against
java-axonframework-example-app copied search_relevant_source's own chunk
formatting ("File: <path>\\nFunction/class: <name>\\n<code>") verbatim into
several submitted files instead of writing a real translation — and because
the copied text was long enough, the old has_impl check (length > 100 chars
only) wrongly counted it as substantive implementation. Also covers
_ddd_scaffolding's dotted-seam-name identifier bug found the same day.
"""

from __future__ import annotations

import json

from micro_cosmos.tools.coder_tools import _ddd_scaffolding, submit_seam_translation
from micro_cosmos.tools.run_context import set_run_dir


def _real_test_file() -> dict:
    return {
        "path": "src/test/kotlin/FooTest.kt",
        "content": "class FooTest {\n    @Test\n    fun testSomething() { assert(true) }\n}\n",
    }


def test_retrieval_artifact_content_is_rejected_as_implementation(tmp_path) -> None:
    set_run_dir(str(tmp_path))
    artifact_content = (
        "File: can-portfolio-soa-app-k8s/03-backend-springboot/property-allocation/"
        "src/main/java/com/customer/can/property/infrastructure/IPortfolioReadRepository.java\n"
        "Function/class: IPortfolioReadRepository\n\n"
        "package com.customer.can.property.infrastructure;\n\n"
        "public interface IPortfolioReadRepository {\n"
        "    java.util.List<Object> findByStatus(String status);\n"
        "}\n"
    )
    result = submit_seam_translation(
        files=[
            {"path": "src/main/kotlin/Foo.kt", "content": artifact_content},
            _real_test_file(),
        ],
        source_path="examples/legacy_estate",
        source_lang="java",
        target_lang="kotlin",
        seam_name="seam_object_prog.PortfolioReadRepository",
        run_dir=str(tmp_path),
    )
    assert result["has_impl"] is False
    assert any("retrieval" in w.lower() or "verbatim" in w.lower() for w in result["warnings"])

    written = json.loads((tmp_path / "seam_result.json").read_text())
    assert written["passed"] is False


def test_real_implementation_is_not_flagged_as_an_artifact(tmp_path) -> None:
    set_run_dir(str(tmp_path))
    real_content = (
        "package com.customer.can.property.infrastructure\n\n"
        "class PortfolioReadRepository {\n"
        + "\n".join(f"    fun method{i}(): Int = {i}" for i in range(10))
        + "\n}\n"
    )
    result = submit_seam_translation(
        files=[
            {"path": "src/main/kotlin/PortfolioReadRepository.kt", "content": real_content},
            _real_test_file(),
        ],
        source_path="examples/legacy_estate",
        source_lang="java",
        target_lang="kotlin",
        seam_name="seam_object_prog.PortfolioReadRepository",
        run_dir=str(tmp_path),
    )
    assert result["has_impl"] is True
    assert not any("retrieval" in w.lower() for w in result["warnings"])


def test_content_starting_with_file_colon_but_not_the_chunk_shape_is_not_a_false_positive(tmp_path) -> None:
    """Only the exact search_relevant_source chunk shape (a "File: " line
    immediately followed by a "Function/class: " line) should trigger this
    — content that merely starts with "File: " for an unrelated reason
    (e.g. a header comment) must not be treated as a copied excerpt."""
    set_run_dir(str(tmp_path))
    real_content = (
        "File: uploaded by the customer at runtime, not a source path.\n\n"
        "package com.example\n\n"
        "class FileHandler {\n"
        + "\n".join(f"    fun method{i}(): Int = {i}" for i in range(10))
        + "\n}\n"
    )
    result = submit_seam_translation(
        files=[
            {"path": "src/main/kotlin/FileHandler.kt", "content": real_content},
            _real_test_file(),
        ],
        source_path="examples/legacy_estate",
        source_lang="java",
        target_lang="kotlin",
        seam_name="seam_object_prog.FileHandler",
        run_dir=str(tmp_path),
    )
    assert result["has_impl"] is True


def test_submit_seam_translation_fills_omitted_args_from_session(tmp_path) -> None:
    """Confirmed live: the model called submit_seam_translation with only the
    files, and Python raised before the body ran because source_path,
    source_lang, target_lang, and seam_name were required. Those four are
    already on the session."""
    set_run_dir(str(tmp_path))
    (tmp_path / "App.java").write_text("class App {}", encoding="utf-8")

    class _Ctx:
        state = {
            "source_path": str(tmp_path),
            "source_lang": "java",
            "target_lang": "rust",
            "current_seam": "seam_from_session",
            "run_dir": str(tmp_path),
        }

    result = submit_seam_translation(
        files=[
            {
                "path": "src/lib.rs",
                "content": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n" * 4,
            },
            {
                "path": "src/lib_test.rs",
                "content": "#[cfg(test)]\nmod tests {\n    #[test]\n    fn adds() {}\n}\n",
            },
        ],
        tool_context=_Ctx(),
    )
    assert result["seam_name"] == "seam_from_session"
    assert result["target_lang"] == "rust"
    written = json.loads((tmp_path / "seam_result.json").read_text())
    assert written["source_lang"] == "java"
    assert written["seam_name"] == "seam_from_session"


def test_ddd_scaffolding_kotlin_dotted_seam_name_produces_valid_identifiers() -> None:
    """Real seam IDs routinely carry a literal "." (e.g.
    "seam_object_prog.PortfolioReadRepository", mirroring the IR's own
    dotted node-id convention). Confirmed live, 2026-08-24: _pascal() only
    split on "_"/"-"/whitespace, so the dot survived straight into the
    generated interface name ("ISeamObjectProg.PortfolioReadRepositoryUseCase")
    — invalid syntax in Kotlin (and every other target language this
    scaffolds for), which a real Gradle/kotlinc run rejected with
    "Redeclaration: interface ISeamObjectProg" plus several "Expecting a
    top level declaration" errors. This is the deterministic
    generate_and_verify_seam() fallback path — since it's not LLM-driven,
    it would regenerate the exact same broken code on every TDD retry,
    guaranteeing the seam could never pass."""
    files = _ddd_scaffolding(
        "seam_object_prog.PortfolioReadRepository", "kotlin", {"aggregates": []}, {},
    )
    content = "\n".join(f["content"] for f in files)
    assert "interface " in content, "expected at least one generated interface"
    for line in content.splitlines():
        if line.strip().startswith("interface "):
            name = line.strip().split()[1]
            assert "." not in name, f"invalid Kotlin identifier: {name!r}"
