"""Tests for Java Axon Framework symbolic parsing and pattern detection."""

from __future__ import annotations

import tempfile
from pathlib import Path
from micro_cosmos.tools.observer_tools import (
    parse_source_estate,
    scan_performance_anti_patterns,
    _parse_java_file,
    _extensions_for,
    _deep_parser_for,
)
from micro_cosmos.tools.pattern_tools import extract_domain_model


def test_parse_java_file_extracts_all_nodes() -> None:
    content = """package com.customer.can.property.domain;

import org.axonframework.commandhandling.CommandHandler;
import org.axonframework.eventsourcing.EventSourcingHandler;
import org.axonframework.modelling.command.AggregateIdentifier;
import org.axonframework.spring.stereotype.Aggregate;

@Aggregate
public class Portfolio {

    @AggregateIdentifier
    private UUID portfolioId;

    private boolean closed;

    @CommandHandler
    public Portfolio(CreatePortfolio cmd) {
        AggregateLifecycle.apply(new PortfolioCreated(cmd.portfolioId()));
    }

    @CommandHandler
    public void handle(AddPropertyToPortfolio cmd) {
        AggregateLifecycle.apply(new PropertyAddedToPortfolio(cmd.propertyId()));
    }

    @EventSourcingHandler
    void on(PortfolioCreated e) {
        this.portfolioId = e.portfolioId();
    }
}
"""
    nodes, edges = _parse_java_file("Portfolio.java", content, "prog.Portfolio")

    # Verify Class
    classes = [n for n in nodes if n.type == "DATA_STRUCTURE"]
    assert len(classes) == 1
    cls = classes[0]
    assert cls.name == "Portfolio"
    assert cls.attributes.get("is_axon_aggregate") == "true"

    # Verify Fields
    fields = [n for n in nodes if n.type == "DATA_ITEM"]
    assert len(fields) == 2
    f_id = [f for f in fields if f.name == "portfolioId"][0]
    assert f_id.attributes.get("is_aggregate_identifier") == "true"
    assert f_id.attributes.get("type") == "UUID"

    # Verify Handlers
    methods = [n for n in nodes if n.type == "PROCEDURE"]
    assert len(methods) == 3
    
    # Check creation handler
    c_handler = [m for m in methods if m.name == "Portfolio"][0]
    assert c_handler.attributes.get("handler_type") == "command"
    assert c_handler.attributes.get("handles_payload") == "CreatePortfolio"

    # Check command handle method
    cmd_handler = [m for m in methods if m.name == "handle"][0]
    assert cmd_handler.attributes.get("handler_type") == "command"
    assert cmd_handler.attributes.get("handles_payload") == "AddPropertyToPortfolio"

    # Check event handler
    evt_handler = [m for m in methods if m.name == "on"][0]
    assert evt_handler.attributes.get("handler_type") == "event-sourcing"
    assert evt_handler.attributes.get("handles_payload") == "PortfolioCreated"

    # Check that implicit reference edges were created
    payload_edges = [e for e in edges if e.type == "REFERENCES"]
    targets = {e.target_id for e in payload_edges}
    assert "class.CreatePortfolio" in targets
    assert "class.AddPropertyToPortfolio" in targets
    assert "class.PortfolioCreated" in targets


def test_sql_file_parsing_extracts_tables() -> None:
    sql = """
    CREATE TABLE CAN_PORTFOLIO (
        id UUID PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        status VARCHAR(50) NOT NULL
    );
    """
    nodes, edges = _parse_java_file("schema.sql", sql, "prog.Schema")
    tables = [n for n in nodes if n.type == "DATA_STRUCTURE"]
    assert len(tables) == 1
    assert tables[0].name == "CAN_PORTFOLIO"
    assert tables[0].attributes.get("kind") == "table"


def test_axon_scanners_find_issues() -> None:
    # 1. Test missing aggregate identifier
    ir_missing_id = {
        "nodes": [
            {
                "id": "class.BadAggregate",
                "type": "DATA_STRUCTURE",
                "name": "BadAggregate",
                "source_location": "BadAggregate.java:8",
                "attributes": {
                    "is_axon_aggregate": "true"
                }
            },
            {
                "id": "field.BadAggregate.someField",
                "type": "DATA_ITEM",
                "name": "someField",
                "source_location": "BadAggregate.java:10",
                "attributes": {
                    "class": "BadAggregate",
                    "type": "String",
                    "is_aggregate_identifier": "false"
                }
            }
        ],
        "edges": []
    }
    
    findings = scan_performance_anti_patterns(ir_missing_id)["performance_findings"]
    patterns = {f["pattern"] for f in findings}
    assert "MISSING_AGGREGATE_IDENTIFIER" in patterns

    # 2. Test direct repository autowiring inside aggregate (bypass command gateway)
    ir_bypass = {
        "nodes": [
            {
                "id": "class.BypassAggregate",
                "type": "DATA_STRUCTURE",
                "name": "BypassAggregate",
                "source_location": "BypassAggregate.java:8",
                "attributes": {
                    "is_axon_aggregate": "true"
                }
            },
            {
                "id": "field.BypassAggregate.portfolioRepository",
                "type": "DATA_ITEM",
                "name": "portfolioRepository",
                "source_location": "BypassAggregate.java:10",
                "attributes": {
                    "class": "BypassAggregate",
                    "type": "PortfolioReadRepository",
                    "is_aggregate_identifier": "false"
                }
            }
        ],
        "edges": []
    }
    findings2 = scan_performance_anti_patterns(ir_bypass)["performance_findings"]
    patterns2 = {f["pattern"] for f in findings2}
    assert "BYPASS_COMMAND_GATEWAY" in patterns2


def test_bare_annotation_not_imported_from_axon_is_ignored() -> None:
    """A same-named @CommandHandler/@Aggregate that does NOT resolve to an
    org.axonframework.* import (e.g. a hand-rolled annotation, or one from an
    unrelated library) must not be mistaken for real Axon usage."""
    content = """package com.example;

@Aggregate
public class NotAnAggregate {

    @CommandHandler
    public void handle(SomeCommand cmd) {
    }
}
"""
    nodes, _edges = _parse_java_file("NotAnAggregate.java", content, "prog.NotAnAggregate")

    cls = [n for n in nodes if n.type == "DATA_STRUCTURE"][0]
    assert cls.attributes.get("is_axon_aggregate") is None

    method = [n for n in nodes if n.type == "PROCEDURE" and n.name == "handle"][0]
    assert method.attributes.get("handler_type") is None


def test_overload_dedup_id_assignment_follows_source_order_not_regex_pass_order() -> None:
    """PR #27 review (Samuel Mbah): _JAVA_METHOD_RE (modifier-bearing methods) and
    _JAVA_PKG_METHOD_RE (annotated, no-modifier methods) used to be iterated as two
    fully-sequential passes. Two overloads of the same handler name (Axon's own
    @EventSourcingHandler convention is to name every handler "on") can be split
    across the two patterns if one overload has an access modifier and another
    doesn't — a realistic inconsistency in customer code. Running one pattern's
    matches to completion before the other started meant a later-in-file,
    modifier-bearing overload could claim the unsuffixed method_id ahead of an
    earlier-in-file package-private one, regardless of true source order — pushing
    the real first-declared handler onto an unpredictable suffixed id.

    Here `on(FirstEvent e)` (package-private, line 6) is declared BEFORE
    `on(SecondEvent e)` (public, line 10) in the source. The plain `on` id must go
    to the first-declared one (FirstEvent), not whichever regex pattern's matches
    happened to be visited first."""
    content = """package com.example;

import org.axonframework.eventsourcing.EventSourcingHandler;

public class Portfolio {

    @EventSourcingHandler
    void on(FirstEvent e) {
    }

    @EventSourcingHandler
    public void on(SecondEvent e) {
    }
}
"""
    nodes, _edges = _parse_java_file("Portfolio.java", content, "prog.Portfolio")
    on_methods = [n for n in nodes if n.type == "PROCEDURE" and n.name == "on"]
    assert len(on_methods) == 2

    plain = [n for n in on_methods if n.id == "method.Portfolio.on"]
    assert len(plain) == 1, f"expected exactly one unsuffixed 'on' id, got: {[n.id for n in on_methods]}"
    assert plain[0].attributes.get("handles_payload") == "FirstEvent", (
        "the unsuffixed method_id must go to the first-declared overload in "
        "source order, regardless of which regex pattern matched it"
    )

    suffixed = [n for n in on_methods if n.id != "method.Portfolio.on"]
    assert len(suffixed) == 1
    assert suffixed[0].attributes.get("handles_payload") == "SecondEvent"


def test_wildcard_axon_import_still_resolves_annotations() -> None:
    """PR #27 follow-up review: _java_import_map's exact-name regex can't match
    a wildcard import (`import org.axonframework.commandhandling.*;`), so a
    codebase using that style got zero Axon detection at all. Fixed by also
    checking, for the fixed set of known Axon annotation names, whether any
    wildcard-imported package is itself under org.axonframework.*."""
    content = """package com.example;

import org.axonframework.commandhandling.*;
import org.axonframework.spring.stereotype.*;

@Aggregate
public class Order {
    @CommandHandler
    public Order(CreateOrder cmd) {}
}
"""
    nodes, _edges = _parse_java_file("Order.java", content, "prog.Order")
    cls = [n for n in nodes if n.type == "DATA_STRUCTURE"][0]
    assert cls.attributes.get("is_axon_aggregate") == "true"
    ctor = [n for n in nodes if n.type == "PROCEDURE" and n.name == "Order"][0]
    assert ctor.attributes.get("handler_type") == "command"


def test_nested_type_does_not_steal_ownership_of_outer_class_members() -> None:
    """PR #27 follow-up review: _owner_class used to resolve ownership by "last
    class-like declaration before this position" with no brace tracking, so a
    nested enum/inner class declared earlier in the same outer class stole
    ownership of everything textually after it — including the outer class's
    own constructor and fields — right up until the end of the file (not just
    until the nested type's own closing brace). This silently dropped real
    Axon constructors from the IR graph and could fire false-positive CRITICAL
    MISSING_AGGREGATE_IDENTIFIER findings on correctly-annotated aggregates."""
    content = """package com.example;

import org.axonframework.commandhandling.CommandHandler;
import org.axonframework.eventsourcing.EventSourcingHandler;
import org.axonframework.modelling.command.AggregateIdentifier;
import org.axonframework.spring.stereotype.Aggregate;

@Aggregate
public class Order {
    enum Status { NEW, SHIPPED }

    @AggregateIdentifier
    private String id;

    @CommandHandler
    public Order(CreateOrder cmd) {}

    @EventSourcingHandler
    void on(OrderCreated e) {}
}
"""
    nodes, _edges = _parse_java_file("Order.java", content, "prog.Order")

    ctor = [n for n in nodes if n.type == "PROCEDURE" and n.name == "Order"]
    assert len(ctor) == 1 and ctor[0].id == "method.Order.Order", (
        f"constructor misattributed to nested type, got: {[n.id for n in nodes if n.type == 'PROCEDURE']}"
    )
    assert ctor[0].attributes.get("handler_type") == "command"

    field = [n for n in nodes if n.type == "DATA_ITEM" and n.name == "id"][0]
    assert field.attributes.get("class") == "Order"
    assert field.attributes.get("is_aggregate_identifier") == "true"

    on_method = [n for n in nodes if n.type == "PROCEDURE" and n.name == "on"][0]
    assert on_method.id == "method.Order.on"

    # The false-positive this bug could cause: MISSING_AGGREGATE_IDENTIFIER
    # firing even though @AggregateIdentifier is genuinely present.
    ir = {"nodes": [n.model_dump(mode="json") for n in nodes], "edges": []}
    findings = scan_performance_anti_patterns(ir)["performance_findings"]
    patterns = {f["pattern"] for f in findings}
    assert "MISSING_AGGREGATE_IDENTIFIER" not in patterns


def test_sql_files_are_discovered_alongside_java_for_a_java_estate() -> None:
    """PR #27 follow-up review: the restored CREATE TABLE parsing branch in
    _parse_java_file was unreachable dead code — _LANG_EXTENSIONS was never
    updated to include .sql for any Java variant, so a real pipeline run's
    file-discovery step never handed a .sql file to any parser at all."""
    for lang in ("java", "java8", "java11", "java21"):
        exts = _extensions_for(lang)
        assert ".java" in exts
        assert ".sql" in exts, f"{lang} extensions missing .sql: {exts}"
    assert _deep_parser_for("java21") is _parse_java_file


def test_create_table_regex_handles_if_not_exists_and_schema_prefix() -> None:
    """PR #27 follow-up review: the CREATE TABLE regex blindly captured the
    next bare word after TABLE, mis-parsing 'IF NOT EXISTS' as the table name
    and truncating a schema-qualified name (dbo.Orders) down to just the
    schema. Also: table nodes now use a table.<name> id, not class.<name> —
    the old id let a SQL table silently collide with a same-named Java class."""
    sql = """
CREATE TABLE IF NOT EXISTS orders (id UUID PRIMARY KEY);
CREATE TABLE dbo.Customers (id UUID PRIMARY KEY);
CREATE TABLE `quoted_table` (id UUID PRIMARY KEY);
"""
    nodes, _edges = _parse_java_file("schema.sql", sql, "prog.Schema")
    by_name = {n.name: n.id for n in nodes}
    assert by_name.get("orders") == "table.orders"
    assert by_name.get("Customers") == "table.Customers"
    assert by_name.get("quoted_table") == "table.quoted_table"
    assert "IF" not in by_name
    assert "dbo" not in by_name


def test_saga_annotations_are_parsed() -> None:
    """@Saga / @SagaEventHandler / @StartSaga / @EndSaga were absent from the
    recognised Axon annotation set, so AllocationSaga.java — the estate's only process
    manager, and the highest-effort construct in an event-sourced migration — produced
    no IR signal at all (BUG-2)."""
    src_java = """
package com.example;
import org.axonframework.spring.stereotype.Saga;
import org.axonframework.modelling.saga.SagaEventHandler;
import org.axonframework.modelling.saga.StartSaga;
import org.axonframework.modelling.saga.EndSaga;

@Saga
public class AllocationSaga {
    @StartSaga
    @SagaEventHandler(associationProperty = "portfolioId")
    public void on(PropertyAddedToPortfolio event) { }

    @EndSaga
    @SagaEventHandler(associationProperty = "portfolioId")
    public void on(ValuationSubmitted event) { }
}
"""
    nodes, _edges = _parse_java_file("AllocationSaga.java", src_java, "prog.AllocationSaga")

    saga_classes = [n for n in nodes if (n.attributes or {}).get("is_axon_saga") == "true"]
    assert saga_classes, "expected @Saga to mark the class as an Axon saga"

    handlers = [n for n in nodes if (n.attributes or {}).get("handler_type") == "saga-event"]
    assert len(handlers) == 2, f"expected 2 @SagaEventHandler methods, got {len(handlers)}"
    payloads = {(n.attributes or {}).get("handles_payload") for n in handlers}
    assert payloads == {"PropertyAddedToPortfolio", "ValuationSubmitted"}


def test_non_axon_saga_annotation_is_not_matched() -> None:
    """A same-named @Saga from an unrelated library must not be mistaken for Axon —
    the import-resolution gate must still apply to the newly-recognised names."""
    src_java = """
package com.example;
import com.other.framework.Saga;

@Saga
public class NotAnAxonSaga {
    public void handle(String s) { }
}
"""
    nodes, _edges = _parse_java_file("NotAnAxonSaga.java", src_java, "prog.NotAnAxonSaga")
    assert not [n for n in nodes if (n.attributes or {}).get("is_axon_saga") == "true"]


def test_processing_group_is_captured() -> None:
    """@ProcessingGroup names the event processor a handler class belongs to. Two
    classes in different groups are independently deployable and replayable, so the
    group is a real boundary signal — it was not captured at all before."""
    src_java = """
package com.example;
import org.axonframework.config.ProcessingGroup;
import org.axonframework.eventhandling.EventHandler;

@ProcessingGroup("portfolio-projection")
public class PortfolioProjection {
    @EventHandler
    public void on(PortfolioCreated e) { }
}
"""
    nodes, _edges = _parse_java_file("PortfolioProjection.java", src_java, "prog.PortfolioProjection")
    groups = {(n.attributes or {}).get("processing_group") for n in nodes}
    assert "portfolio-projection" in groups


def test_non_axon_processing_group_is_not_matched() -> None:
    src_java = """
package com.example;
import com.other.framework.ProcessingGroup;

@ProcessingGroup("not-axon")
public class Unrelated {
    public void handle(String s) { }
}
"""
    nodes, _edges = _parse_java_file("Unrelated.java", src_java, "prog.Unrelated")
    assert not any((n.attributes or {}).get("processing_group") for n in nodes)
