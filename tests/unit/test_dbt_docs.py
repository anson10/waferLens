"""docs/dbt.md generation from a dbt manifest."""

from __future__ import annotations

from typing import Any

from waferlens.db.dbt_docs import lineage, model_table, render


def _model(name: str, layer: str, parents: list[str], materialized: str = "view") -> dict[str, Any]:
    return {
        "resource_type": "model",
        "package_name": "waferlens",
        "name": name,
        "fqn": ["waferlens", layer, name],
        "depends_on": {"nodes": parents},
        "config": {"materialized": materialized},
        "description": f"{name} description",
    }


MANIFEST: dict[str, Any] = {
    "nodes": {
        "model.waferlens.stg_a": _model("stg_a", "staging", ["source.waferlens.raw.a"]),
        "model.waferlens.stg_b": _model("stg_b", "staging", ["source.waferlens.raw.b"]),
        "model.waferlens.int_x": _model("int_x", "intermediate", ["model.waferlens.stg_a"]),
        "model.waferlens.fct_y": _model(
            "fct_y", "marts", ["model.waferlens.int_x", "model.waferlens.stg_b"], "table"
        ),
        "test.waferlens.unique_fct_y": {
            "resource_type": "test",
            "depends_on": {"nodes": ["model.waferlens.fct_y"]},
        },
        "model.dbt_utils.other": {**_model("other", "marts", []), "package_name": "dbt_utils"},
    },
    "unit_tests": {
        "unit_test.waferlens.fct_y.t": {"depends_on": {"nodes": ["model.waferlens.fct_y"]}}
    },
}


def test_lineage_collapses_staging_and_keeps_model_edges() -> None:
    graph = lineage(MANIFEST)
    assert 'staging["staging<br/>2 views over the source tables"]' in graph
    assert "staging --> int_x" in graph
    assert "int_x --> fct_y" in graph
    assert "staging --> fct_y" in graph
    assert "stg_a" not in graph  # staging models are one node
    assert "other" not in graph  # package models are not ours


def test_model_table_counts_data_and_unit_tests() -> None:
    table = model_table(MANIFEST)
    assert "| `fct_y` | marts | table | 2 | fct_y description |" in table
    assert "| `int_x` | intermediate | view | 0 |" in table
    assert "stg_a" not in table


def test_render_summarises_the_project() -> None:
    doc = render(MANIFEST)
    assert (
        "4 models (2 staging views, 1 intermediate,\n1 marts), 1 data tests and 1 unit tests" in doc
    )
