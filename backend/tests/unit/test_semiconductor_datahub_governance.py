from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any


def _generator() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    return runpy.run_path(str(root / "scripts" / "generate_semiconductor_seed.py"))


def test_semiconductor_taxonomy_is_complete_and_stable() -> None:
    generator = _generator()
    taxonomy = generator["datahub_governance_taxonomy"]()

    assert len(taxonomy.nodes) == 9
    assert len(taxonomy.terms) == 33
    assert len(taxonomy.tags) == 56
    assert len({node.urn for node in taxonomy.nodes}) == len(taxonomy.nodes)
    assert len({term.urn for term in taxonomy.terms}) == len(taxonomy.terms)
    assert len({tag.urn for tag in taxonomy.tags}) == len(taxonomy.tags)
    assert {term.term_id for term in taxonomy.terms} >= {
        "supplier_master",
        "manufacturing_lot",
        "quality_measurement",
        "annual_volume",
        "referenced_record",
    }
    assert {
        tag.name
        for tag in taxonomy.tags
        if tag.tag_id.startswith("datariver_classification_")
    } == {
        "CLASSIFICATION:PUBLIC",
        "CLASSIFICATION:INTERNAL",
        "CLASSIFICATION:CONFIDENTIAL",
        "CLASSIFICATION:RESTRICTED",
    }


def test_generated_dataset_and_field_aspects_have_controlled_semantics() -> None:
    generator = _generator()
    table_specs = generator["build_table_specs"]()
    entities = generator["build_entities"](
        table_specs,
        "dual",
        postgres_database_name="datariver",
        oracle_database_name="ORCL",
    )
    table = next(
        entity
        for entity in entities
        if entity.platform == "postgres"
        and entity.kind == "table"
        and entity.name.startswith("supplier_qualification_")
    )
    view = next(
        entity for entity in entities if entity.platform == "oracle" and entity.kind == "view"
    )

    aspects = dict(generator["aspect_documents"](table, "seed-run"))
    assert set(aspects) == {
        "datasetProperties",
        "globalTags",
        "glossaryTerms",
        "schemaMetadata",
        "upstreamLineage",
    }
    assert "urn:li:glossaryTerm:supplier_qualification" in {
        item["urn"] for item in aspects["glossaryTerms"]["terms"]
    }
    assert "urn:li:tag:datariver_semiconductor" in {
        item["tag"] for item in aspects["globalTags"]["tags"]
    }
    assert not {
        item["tag"]
        for item in aspects["globalTags"]["tags"]
        if item["tag"].startswith("urn:li:tag:datariver_classification_")
    }
    public_aspects = dict(generator["aspect_documents"](table, "seed-run", "PUBLIC"))
    assert "urn:li:tag:datariver_classification_public" in {
        item["tag"] for item in public_aspects["globalTags"]["tags"]
    }
    fields = {item["fieldPath"]: item for item in aspects["schemaMetadata"]["fields"]}
    assert fields["id"]["glossaryTerms"]["terms"] == [
        {"urn": "urn:li:glossaryTerm:record_identifier"}
    ]
    assert fields["annual_volume"]["globalTags"]["tags"] == [
        {"tag": "urn:li:tag:datariver_field_measure_volume"}
    ]
    foreign_key = next(name for name in fields if name.endswith("_id") and name != "id")
    assert fields[foreign_key]["globalTags"]["tags"] == [
        {"tag": "urn:li:tag:datariver_field_reference"}
    ]

    view_aspects = dict(generator["aspect_documents"](view, "seed-run"))
    view_fields = {item["fieldPath"]: item for item in view_aspects["schemaMetadata"]["fields"]}
    assert view_fields["id"]["globalTags"]["tags"] == [
        {"tag": "urn:li:tag:datariver_field_identifier"}
    ]
    assert view_fields["annual_volume"]["glossaryTerms"]["terms"] == [
        {"urn": "urn:li:glossaryTerm:annual_volume"}
    ]
    assert "urn:li:tag:datariver_execution_mock" in {
        item["tag"] for item in view_aspects["globalTags"]["tags"]
    }


def test_vocabulary_proposals_are_typed_and_parent_first() -> None:
    generator = _generator()
    taxonomy = generator["datahub_governance_taxonomy"]()
    documents = generator["governance_aspect_documents"](taxonomy)

    node_count = len(taxonomy.nodes)
    term_count = len(taxonomy.terms)
    assert [document[0] for document in documents[:node_count]] == ["glossaryNode"] * node_count
    assert [document[0] for document in documents[node_count : node_count + term_count]] == [
        "glossaryTerm"
    ] * term_count
    assert all(document[3] == "tagProperties" for document in documents[node_count + term_count :])
    root = documents[0]
    assert root[4]["name"] == "Semiconductor data"
    assert "parentNode" not in root[4]


def test_aspect_reader_accepts_datahub_qualified_aspect_wrapper() -> None:
    generator = _generator()

    assert generator["_aspect_document"](
        {
            "version": 0,
            "aspect": {
                "com.linkedin.glossary.GlossaryNodeInfo": {
                    "name": "Semiconductor data",
                }
            },
        }
    ) == {"name": "Semiconductor data"}
