#!/usr/bin/env python3
# ruff: noqa: E501
"""Build a restartable semiconductor value-chain seed for local DataHub testing.

This tool owns only the ``semiconductor_seed`` PostgreSQL schema.  It never
touches DataRiver application tables and refuses a reset when it finds an
object that was not produced by the current deterministic plan.  PostgreSQL
is applied for real; Oracle is deliberately rendered as a labelled mock
artifact so that local development does not need an Oracle instance.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import httpx

SCHEMA_NAME = "semiconductor_seed"
ENVIRONMENT = "DEV"
DATAHUB_SYSTEM_ACTOR = "urn:li:corpuser:__datahub_system"
DEFAULT_ROWS_PER_TABLE = 20
DEFAULT_BATCH_SIZE = 25
# A local GMS + Elasticsearch stack is typically CPU-bound during index updates.
# Keep this deliberately small; each entity emits three aspects.
DEFAULT_DATAHUB_BATCH_SIZE = 5
SEED_NAMESPACE = uuid.UUID("3a1db548-b76a-48e2-9e8f-2e3a93fe7f2a")


@dataclass(frozen=True)
class Family:
    slug: str
    title: str
    description: str
    parent_slugs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSpec:
    family: Family
    scenario: str
    name: str
    parents: tuple[str, ...]

    @property
    def qualified_name(self) -> str:
        return f"{SCHEMA_NAME}.{self.name}"

    @property
    def view_name(self) -> str:
        return f"vw_{self.name}"

    @property
    def qualified_view_name(self) -> str:
        return f"{SCHEMA_NAME}.{self.view_name}"


@dataclass(frozen=True)
class EntitySpec:
    platform: Literal["postgres", "oracle"]
    database_name: str
    name: str
    qualified_name: str
    kind: Literal["table", "view"]
    description: str
    upstream_qualified_names: tuple[str, ...]
    execution_mode: Literal["APPLIED", "MOCK"]

    @property
    def urn(self) -> str:
        return (
            f"urn:li:dataset:(urn:li:dataPlatform:{self.platform},"
            f"{self.qualified_name},{ENVIRONMENT})"
        )


@dataclass(frozen=True)
class GlossaryNodeSpec:
    node_id: str
    name: str
    definition: str
    parent_node_id: str | None = None

    @property
    def urn(self) -> str:
        return f"urn:li:glossaryNode:{self.node_id}"


@dataclass(frozen=True)
class GlossaryTermSpec:
    term_id: str
    name: str
    definition: str
    parent_node_id: str

    @property
    def urn(self) -> str:
        return f"urn:li:glossaryTerm:{self.term_id}"


@dataclass(frozen=True)
class TagSpec:
    tag_id: str
    name: str
    description: str

    @property
    def urn(self) -> str:
        return f"urn:li:tag:{self.tag_id}"


@dataclass(frozen=True)
class DataHubGovernanceTaxonomy:
    """Controlled semiconductor vocabulary owned by this deterministic seed."""

    nodes: tuple[GlossaryNodeSpec, ...]
    terms: tuple[GlossaryTermSpec, ...]
    tags: tuple[TagSpec, ...]


FAMILIES: tuple[Family, ...] = (
    Family(
        "reference_legal_entity",
        "Legal entity",
        "Registered semiconductor group, subsidiary, and joint-venture records.",
    ),
    Family(
        "reference_facility",
        "Facility",
        "Fabrication, assembly, test, research, and logistics facility records.",
        ("reference_legal_entity",),
    ),
    Family(
        "technology_node",
        "Technology node",
        "Process-node, device architecture, and qualification baseline records.",
        ("reference_facility",),
    ),
    Family(
        "product_master",
        "Product master",
        "Commercial die, package, module, and customer-product master records.",
        ("technology_node",),
    ),
    Family(
        "supplier_master",
        "Supplier master",
        "Material, equipment, design-service, test, and logistics supplier records.",
        ("reference_legal_entity",),
    ),
    Family(
        "supplier_qualification",
        "Supplier qualification",
        "Supplier qualification outcomes against a semiconductor product scope.",
        ("supplier_master", "product_master"),
    ),
    Family(
        "procurement_contract",
        "Procurement contract",
        "Sourcing, pricing, volume, and delivery agreements for product supply.",
        ("supplier_master", "product_master"),
    ),
    Family(
        "purchase_order",
        "Purchase order",
        "Material and equipment purchase orders released from approved contracts.",
        ("procurement_contract",),
    ),
    Family(
        "material_specification",
        "Material specification",
        "Wafer, gas, chemical, mask, substrate, and packaging material specifications.",
        ("supplier_master", "product_master"),
    ),
    Family(
        "logistics_shipment",
        "Logistics shipment",
        "Inbound material, inter-fab transfer, and finished-goods shipment events.",
        ("purchase_order", "reference_facility"),
    ),
    Family(
        "inventory_lot",
        "Inventory lot",
        "Traceable material and finished-good inventory lots by receiving event.",
        ("logistics_shipment", "material_specification"),
    ),
    Family(
        "equipment_asset",
        "Equipment asset",
        "Lithography, deposition, etch, metrology, test, and packaging equipment assets.",
        ("reference_facility",),
    ),
    Family(
        "manufacturing_route",
        "Manufacturing route",
        "Approved process routing from die design to package and test operations.",
        ("product_master",),
    ),
    Family(
        "manufacturing_operation",
        "Manufacturing operation",
        "Operation-level execution targets tied to route and equipment capability.",
        ("manufacturing_route", "equipment_asset"),
    ),
    Family(
        "manufacturing_lot",
        "Manufacturing lot",
        "In-process wafer and assembly lots linked to operations and inventory inputs.",
        ("manufacturing_operation", "inventory_lot"),
    ),
    Family(
        "quality_measurement",
        "Quality measurement",
        "Electrical, physical, reliability, and visual inspection measurement records.",
        ("manufacturing_lot",),
    ),
    Family(
        "yield_summary",
        "Yield summary",
        "Yield, defect, binning, and loss summaries derived from quality measurements.",
        ("quality_measurement",),
    ),
    Family(
        "cost_ledger",
        "Cost ledger",
        "Material, conversion, logistics, test, and yield-loss cost allocations.",
        ("manufacturing_lot", "purchase_order"),
    ),
    Family(
        "capital_project",
        "Capital project",
        "Capacity expansion, equipment investment, and technology-program project records.",
        ("reference_legal_entity", "product_master"),
    ),
    Family(
        "research_market_signal",
        "Research and market signal",
        "Curated news, paper, patent, analyst, and market intelligence observations.",
        ("technology_node", "product_master"),
    ),
)

SCENARIOS: tuple[str, ...] = (
    "logic_3nm",
    "logic_5nm",
    "logic_7nm",
    "memory_dram",
    "memory_hbm",
    "memory_nand",
    "power_sic",
    "power_gan",
    "analog_mixed_signal",
    "image_sensor",
    "rf_connectivity",
    "automotive_mcu",
    "automotive_adas",
    "industrial_iot",
    "ai_accelerator",
    "edge_ai",
    "data_center",
    "advanced_package",
    "chiplet_interconnect",
    "wafer_materials",
    "photoresist",
    "etch_deposition",
    "lithography",
    "test_osat",
    "global_logistics",
)


# The glossary follows business meaning, rather than mirroring physical table
# names.  Every generated dataset has one family term and a scenario term;
# PostgreSQL table fields additionally receive the common-record semantics
# below.  Tag identifiers are deliberately ASCII-safe DataHub URN fragments
# while their names remain human-readable in the UI.
GLOSSARY_ROOT = "datariver_semiconductor"
GLOSSARY_NODES: tuple[GlossaryNodeSpec, ...] = (
    GlossaryNodeSpec(
        GLOSSARY_ROOT,
        "Semiconductor data",
        "Controlled vocabulary for the deterministic semiconductor value-chain seed.",
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_business_foundation",
        "Business foundation",
        "Reference entities that define enterprise, facility, technology, and product scope.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_supply",
        "Supply and procurement",
        "Supplier qualification, sourcing, contracting, purchasing, and material semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_logistics",
        "Logistics and inventory",
        "Physical movement, receiving, transfer, and inventory traceability semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_manufacturing",
        "Manufacturing operations",
        "Equipment, routing, operation, and in-process semiconductor production semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_quality",
        "Quality and yield",
        "Measurement, defect, reliability, binning, and yield semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_finance",
        "Finance and capital",
        "Cost allocation, capacity investment, and technology-program semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_intelligence",
        "Research and market intelligence",
        "Curated research, patent, analyst, news, and market-observation semantics.",
        GLOSSARY_ROOT,
    ),
    GlossaryNodeSpec(
        "datariver_semiconductor_cross_cutting",
        "Cross-cutting record semantics",
        "Identifier, lifecycle, geography, measure, date, and audit semantics shared by all seed tables.",
        GLOSSARY_ROOT,
    ),
)

STAGE_FOR_FAMILY: dict[str, tuple[str, str, str]] = {
    "reference_legal_entity": (
        "datariver_semiconductor_business_foundation",
        "business_foundation",
        "Business foundation",
    ),
    "reference_facility": (
        "datariver_semiconductor_business_foundation",
        "business_foundation",
        "Business foundation",
    ),
    "technology_node": (
        "datariver_semiconductor_business_foundation",
        "business_foundation",
        "Business foundation",
    ),
    "product_master": (
        "datariver_semiconductor_business_foundation",
        "business_foundation",
        "Business foundation",
    ),
    "supplier_master": ("datariver_semiconductor_supply", "supply", "Supply and procurement"),
    "supplier_qualification": (
        "datariver_semiconductor_supply",
        "supply",
        "Supply and procurement",
    ),
    "procurement_contract": (
        "datariver_semiconductor_supply",
        "supply",
        "Supply and procurement",
    ),
    "purchase_order": ("datariver_semiconductor_supply", "supply", "Supply and procurement"),
    "material_specification": (
        "datariver_semiconductor_supply",
        "supply",
        "Supply and procurement",
    ),
    "logistics_shipment": (
        "datariver_semiconductor_logistics",
        "logistics",
        "Logistics and inventory",
    ),
    "inventory_lot": (
        "datariver_semiconductor_logistics",
        "logistics",
        "Logistics and inventory",
    ),
    "equipment_asset": (
        "datariver_semiconductor_manufacturing",
        "manufacturing",
        "Manufacturing operations",
    ),
    "manufacturing_route": (
        "datariver_semiconductor_manufacturing",
        "manufacturing",
        "Manufacturing operations",
    ),
    "manufacturing_operation": (
        "datariver_semiconductor_manufacturing",
        "manufacturing",
        "Manufacturing operations",
    ),
    "manufacturing_lot": (
        "datariver_semiconductor_manufacturing",
        "manufacturing",
        "Manufacturing operations",
    ),
    "quality_measurement": (
        "datariver_semiconductor_quality",
        "quality",
        "Quality and yield",
    ),
    "yield_summary": (
        "datariver_semiconductor_quality",
        "quality",
        "Quality and yield",
    ),
    "cost_ledger": (
        "datariver_semiconductor_finance",
        "finance",
        "Finance and capital",
    ),
    "capital_project": (
        "datariver_semiconductor_finance",
        "finance",
        "Finance and capital",
    ),
    "research_market_signal": (
        "datariver_semiconductor_intelligence",
        "intelligence",
        "Research and market intelligence",
    ),
}

FIELD_TERMS: tuple[GlossaryTermSpec, ...] = (
    GlossaryTermSpec(
        "record_identifier",
        "Record identifier",
        "Stable synthetic record identifier.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "semiconductor_scenario",
        "Semiconductor scenario",
        "Technology, product, or value-chain scenario used to partition the synthetic reference set.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "business_key",
        "Business key",
        "Human-readable unique key for a business record.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "record_name",
        "Record name",
        "Display name of the modeled business record.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "lifecycle_status",
        "Lifecycle status",
        "Qualification, release, active, or review state of a business record.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "operational_region",
        "Operational region",
        "Operational geography associated with the record.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "annual_volume",
        "Annual volume",
        "Annualized synthetic quantity for capacity, demand, supply, or activity analysis.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "unit_cost",
        "Unit cost",
        "Synthetic unit cost used only for local scenario analysis.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "effective_date",
        "Effective date",
        "Date from which the record values are effective.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "active_indicator",
        "Active indicator",
        "Boolean indicating whether the modeled record is active.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "created_timestamp",
        "Created timestamp",
        "Timestamp at which the synthetic record was created.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "updated_timestamp",
        "Updated timestamp",
        "Timestamp at which the synthetic record was last updated.",
        "datariver_semiconductor_cross_cutting",
    ),
    GlossaryTermSpec(
        "referenced_record",
        "Referenced record",
        "Display value resolved through a modeled parent-record relationship.",
        "datariver_semiconductor_cross_cutting",
    ),
)

FIELD_SEMANTICS: dict[str, tuple[str, str]] = {
    "id": ("record_identifier", "identifier"),
    "scenario_code": ("semiconductor_scenario", "scenario"),
    "business_key": ("business_key", "business_key"),
    "record_name": ("record_name", "business_attribute"),
    "lifecycle_status": ("lifecycle_status", "lifecycle"),
    "operational_region": ("operational_region", "geography"),
    "annual_volume": ("annual_volume", "measure_volume"),
    "unit_cost": ("unit_cost", "measure_cost"),
    "effective_date": ("effective_date", "effective_date"),
    "is_active": ("active_indicator", "lifecycle"),
    "created_at": ("created_timestamp", "audit_timestamp"),
    "updated_at": ("updated_timestamp", "audit_timestamp"),
}


def datahub_governance_taxonomy() -> DataHubGovernanceTaxonomy:
    """Return the fixed vocabulary and tags expected by the seed workflow."""
    family_terms = tuple(
        GlossaryTermSpec(
            family.slug,
            family.title,
            family.description,
            STAGE_FOR_FAMILY[family.slug][0],
        )
        for family in FAMILIES
    )
    stage_tags = tuple(
        TagSpec(
            f"datariver_value_chain_{stage_id}",
            f"Value chain · {label}",
            f"Synthetic semiconductor asset in the {label.casefold()} value-chain stage.",
        )
        for _, stage_id, label in sorted(set(STAGE_FOR_FAMILY.values()), key=lambda value: value[1])
    )
    static_tags = (
        TagSpec(
            "datariver_semiconductor",
            "Semiconductor",
            "Semiconductor-domain synthetic reference metadata.",
        ),
        TagSpec(
            "datariver_seed", "DataRiver seed", "DataRiver-controlled deterministic seed metadata."
        ),
        TagSpec(
            "datariver_synthetic",
            "Synthetic",
            "Synthetic data; never an externally verified business fact.",
        ),
        TagSpec("datariver_object_table", "Dataset · table", "Physical modeled table."),
        TagSpec("datariver_object_view", "Dataset · view", "Derived modeled view."),
        TagSpec(
            "datariver_execution_applied",
            "Execution · applied",
            "Metadata for a real local PostgreSQL seed object.",
        ),
        TagSpec(
            "datariver_execution_mock",
            "Execution · mock",
            "Metadata for an explicitly labelled Oracle mock object.",
        ),
        TagSpec(
            "datariver_platform_postgres",
            "Platform · PostgreSQL",
            "PostgreSQL synthetic seed metadata.",
        ),
        TagSpec(
            "datariver_platform_oracle", "Platform · Oracle", "Oracle mock synthetic seed metadata."
        ),
        TagSpec(
            "datariver_field_identifier", "Field · identifier", "Identifier or primary-key field."
        ),
        TagSpec("datariver_field_scenario", "Field · scenario", "Semiconductor scenario field."),
        TagSpec("datariver_field_business_key", "Field · business key", "Business-key field."),
        TagSpec(
            "datariver_field_business_attribute",
            "Field · business attribute",
            "Business display or descriptive attribute.",
        ),
        TagSpec(
            "datariver_field_lifecycle", "Field · lifecycle", "Lifecycle or active-status field."
        ),
        TagSpec("datariver_field_geography", "Field · geography", "Operational-geography field."),
        TagSpec(
            "datariver_field_measure_volume",
            "Field · volume measure",
            "Annualized quantity measure.",
        ),
        TagSpec(
            "datariver_field_measure_cost", "Field · cost measure", "Synthetic unit-cost measure."
        ),
        TagSpec(
            "datariver_field_effective_date", "Field · effective date", "Effective-date field."
        ),
        TagSpec(
            "datariver_field_audit_timestamp",
            "Field · audit timestamp",
            "Created or updated audit timestamp.",
        ),
        TagSpec(
            "datariver_field_reference",
            "Field · relationship reference",
            "Parent-record reference or joined reference field.",
        ),
    )
    scenario_tags = tuple(
        TagSpec(
            f"datariver_scenario_{scenario}",
            f"Scenario · {scenario.replace('_', ' ')}",
            "Synthetic semiconductor scenario used by this dataset.",
        )
        for scenario in SCENARIOS
    )
    return DataHubGovernanceTaxonomy(
        nodes=GLOSSARY_NODES,
        terms=tuple(sorted((*family_terms, *FIELD_TERMS), key=lambda term: term.term_id)),
        tags=tuple(sorted((*static_tags, *stage_tags, *scenario_tags), key=lambda tag: tag.tag_id)),
    )


def quote_identifier(value: str) -> str:
    """Quote an internally generated SQL identifier."""
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def build_table_specs() -> tuple[TableSpec, ...]:
    by_family_scenario: dict[tuple[str, str], str] = {}
    table_specs: list[TableSpec] = []
    for family in FAMILIES:
        for scenario in SCENARIOS:
            name = f"{family.slug}_{scenario}"
            parents = tuple(
                by_family_scenario[(parent, scenario)] for parent in family.parent_slugs
            )
            table_specs.append(
                TableSpec(family=family, scenario=scenario, name=name, parents=parents)
            )
            by_family_scenario[(family.slug, scenario)] = name
    return tuple(table_specs)


def seed_uuid(namespace: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, namespace)


def record_id(table_name: str, row_number: int) -> uuid.UUID:
    return seed_uuid(f"postgres:{SCHEMA_NAME}:{table_name}:{row_number}")


def common_columns(spec: TableSpec) -> tuple[tuple[str, str, str], ...]:
    foreign_keys = tuple(
        (
            f"{parent}_id",
            "uuid",
            f"NOT NULL REFERENCES {quote_identifier(SCHEMA_NAME)}.{quote_identifier(parent)}(id)",
        )
        for parent in spec.parents
    )
    return (
        ("id", "uuid", "PRIMARY KEY"),
        ("scenario_code", "text", "NOT NULL"),
        ("business_key", "text", "NOT NULL UNIQUE"),
        ("record_name", "text", "NOT NULL"),
        ("lifecycle_status", "text", "NOT NULL"),
        ("operational_region", "text", "NOT NULL"),
        ("annual_volume", "integer", "NOT NULL"),
        ("unit_cost", "numeric(14,2)", "NOT NULL"),
        ("effective_date", "date", "NOT NULL"),
        ("is_active", "boolean", "NOT NULL"),
        *foreign_keys,
        ("created_at", "timestamptz", "NOT NULL"),
        ("updated_at", "timestamptz", "NOT NULL"),
    )


def create_table_sql(spec: TableSpec) -> str:
    columns = ",\n    ".join(
        f"{quote_identifier(name)} {data_type} {constraint}".rstrip()
        for name, data_type, constraint in common_columns(spec)
    )
    return (
        f"CREATE TABLE {quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.name)} (\n"
        f"    {columns}\n"
        ");"
    )


def create_view_sql(spec: TableSpec) -> str:
    child = f"{quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.name)}"
    selected = [
        "child.id",
        "child.business_key",
        "child.record_name",
        "child.scenario_code",
        "child.lifecycle_status",
        "child.operational_region",
        "child.annual_volume",
        "child.unit_cost",
        "child.effective_date",
    ]
    joins: list[str] = []
    for parent_number, parent in enumerate(spec.parents, start=1):
        alias = f"parent_{parent_number}"
        selected.append(f"{alias}.record_name AS {alias}_name")
        joins.append(
            f"LEFT JOIN {quote_identifier(SCHEMA_NAME)}.{quote_identifier(parent)} AS {alias} "
            f"ON child.{quote_identifier(f'{parent}_id')} = {alias}.id"
        )
    join_sql = "\n".join(joins)
    selected_sql = ",\n    ".join(selected)
    joins_sql = f"\n{join_sql}" if join_sql else ""
    return (
        f"CREATE VIEW {quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.view_name)} AS\n"
        f"SELECT\n    {selected_sql}\nFROM {child} AS child{joins_sql};"
    )


def row_values(spec: TableSpec, row_number: int, rows_per_table: int) -> tuple[Any, ...]:
    baseline = datetime(2026, 1, 1, tzinfo=UTC)
    regions = ("KR", "TW", "US", "JP", "EU")
    values: list[Any] = [
        record_id(spec.name, row_number),
        spec.scenario,
        f"{spec.name.upper()}-{row_number:03d}",
        f"{spec.family.title} / {spec.scenario.replace('_', ' ')} / {row_number:03d}",
        ("qualified", "released", "active", "review")[row_number % 4],
        regions[row_number % len(regions)],
        1_000 + row_number * 137,
        Decimal("125.00") + Decimal(row_number) * Decimal("7.25"),
        date(2026, 1, 1) + timedelta(days=row_number),
        row_number % 11 != 0,
    ]
    values.extend(
        record_id(parent, (row_number - 1) % rows_per_table + 1) for parent in spec.parents
    )
    values.extend(
        (baseline + timedelta(minutes=row_number), baseline + timedelta(minutes=row_number))
    )
    return tuple(values)


def insert_sql(spec: TableSpec) -> str:
    columns = common_columns(spec)
    names = ", ".join(quote_identifier(name) for name, _, _ in columns)
    parameters = ", ".join(f"${number}" for number in range(1, len(columns) + 1))
    return (
        f"INSERT INTO {quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.name)} "  # noqa: S608
        f"({names}) VALUES ({parameters})"
    )


def oracle_type(postgres_type: str) -> str:
    if postgres_type == "uuid":
        return "VARCHAR2(36)"
    if postgres_type == "text":
        return "VARCHAR2(400)"
    if postgres_type == "integer":
        return "NUMBER(10)"
    if postgres_type.startswith("numeric"):
        return "NUMBER(14,2)"
    if postgres_type == "date":
        return "DATE"
    if postgres_type == "boolean":
        return "NUMBER(1)"
    if postgres_type == "timestamptz":
        return "TIMESTAMP WITH TIME ZONE"
    raise ValueError(f"No Oracle type mapping for {postgres_type!r}")


def oracle_table_sql(spec: TableSpec) -> str:
    columns: list[str] = []
    for name, postgres_type, constraint in common_columns(spec):
        if name.endswith("_id") and name != "id":
            parent = name.removesuffix("_id")
            oracle_constraint = (
                f'NOT NULL REFERENCES "{SCHEMA_NAME.upper()}"."{parent.upper()}"("ID")'
            )
        else:
            oracle_constraint = constraint
        columns.append(f'"{name.upper()}" {oracle_type(postgres_type)} {oracle_constraint}')
    return (
        f'CREATE TABLE "{SCHEMA_NAME.upper()}"."{spec.name.upper()}" (\n    '
        + ",\n    ".join(columns)
        + "\n);\n"
    )


def oracle_view_sql(spec: TableSpec) -> str:
    child = f'"{SCHEMA_NAME.upper()}"."{spec.name.upper()}"'
    selected = [
        'child."ID"',
        'child."BUSINESS_KEY"',
        'child."RECORD_NAME"',
        'child."SCENARIO_CODE"',
        'child."LIFECYCLE_STATUS"',
        'child."OPERATIONAL_REGION"',
        'child."ANNUAL_VOLUME"',
        'child."UNIT_COST"',
        'child."EFFECTIVE_DATE"',
    ]
    joins: list[str] = []
    for parent_number, parent in enumerate(spec.parents, start=1):
        alias = f"parent_{parent_number}"
        selected.append(f'{alias}."RECORD_NAME" AS {alias}_name')
        joins.append(
            f'LEFT JOIN "{SCHEMA_NAME.upper()}"."{parent.upper()}" {alias} '
            f'ON child."{parent.upper()}_ID" = {alias}."ID"'
        )
    selected_sql = ",\n    ".join(selected)
    join_sql = f"\n{'\n'.join(joins)}" if joins else ""
    return (
        f'CREATE VIEW "{SCHEMA_NAME.upper()}"."{spec.view_name.upper()}" AS\n'
        f"SELECT\n    {selected_sql}\nFROM {child} child{join_sql};"
    )


def build_entities(
    table_specs: Sequence[TableSpec],
    scope: Literal["postgres", "dual"],
    *,
    postgres_database_name: str,
    oracle_database_name: str,
) -> tuple[EntitySpec, ...]:
    platforms: tuple[Literal["postgres", "oracle"], ...] = (
        ("postgres", "oracle") if scope == "dual" else ("postgres",)
    )
    entities: list[EntitySpec] = []
    for platform in platforms:
        database_name = postgres_database_name if platform == "postgres" else oracle_database_name
        execution_mode: Literal["APPLIED", "MOCK"] = "APPLIED" if platform == "postgres" else "MOCK"
        for table in table_specs:
            entities.append(
                EntitySpec(
                    platform=platform,
                    database_name=database_name,
                    name=table.name,
                    qualified_name=table.qualified_name,
                    kind="table",
                    description=(
                        f"{table.family.description} Scenario: {table.scenario}. "
                        f"DataRiver semiconductor seed ({execution_mode.lower()})."
                    ),
                    upstream_qualified_names=tuple(
                        f"{SCHEMA_NAME}.{parent}" for parent in table.parents
                    ),
                    execution_mode=execution_mode,
                )
            )
            entities.append(
                EntitySpec(
                    platform=platform,
                    database_name=database_name,
                    name=table.view_name,
                    qualified_name=table.qualified_view_name,
                    kind="view",
                    description=(
                        f"Analytic projection over {table.qualified_name} with explicit "
                        f"foreign-key lineage. DataRiver semiconductor seed ({execution_mode.lower()})."
                    ),
                    upstream_qualified_names=(
                        table.qualified_name,
                        *(f"{SCHEMA_NAME}.{parent}" for parent in table.parents),
                    ),
                    execution_mode=execution_mode,
                )
            )
    return tuple(entities)


def json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def previous_postgres_state(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    postgres = document.get("postgres")
    return postgres if isinstance(postgres, dict) else {}


def write_oracle_mock(output_directory: Path, table_specs: Sequence[TableSpec]) -> None:
    oracle_directory = output_directory / "oracle-mock"
    oracle_directory.mkdir(parents=True, exist_ok=True)
    ddl_path = oracle_directory / "semiconductor_seed_oracle_mock.sql"
    reset_lines = [
        "-- This is a generated Oracle MOCK artifact. It was not executed by the local workflow.",
        f'CREATE USER "{SCHEMA_NAME.upper()}" IDENTIFIED BY change_me;',
        f'ALTER USER "{SCHEMA_NAME.upper()}" QUOTA UNLIMITED ON USERS;',
        "",
    ]
    for table in reversed(table_specs):
        reset_lines.append(
            "BEGIN EXECUTE IMMEDIATE 'DROP VIEW \""
            + SCHEMA_NAME.upper()
            + '"."'
            + table.view_name.upper()
            + "\"'; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END; /"
        )
    for table in reversed(table_specs):
        reset_lines.append(
            "BEGIN EXECUTE IMMEDIATE 'DROP TABLE \""
            + SCHEMA_NAME.upper()
            + '"."'
            + table.name.upper()
            + "\" CASCADE CONSTRAINTS'; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END; /"
        )
    ddl_path.write_text(
        "\n".join(reset_lines)
        + "\n\n"
        + "\n\n".join(oracle_table_sql(spec) for spec in table_specs)
        + "\n\n"
        + "\n\n".join(oracle_view_sql(spec) for spec in table_specs)
        + "\n",
        encoding="utf-8",
    )
    write_json(
        oracle_directory / "manifest.json",
        {
            "schema": SCHEMA_NAME,
            "execution_mode": "MOCK",
            "tables": len(table_specs),
            "views": len(table_specs),
            "rows_per_table": "not executed",
            "ddl": str(ddl_path),
        },
    )


async def existing_seed_objects(connection: asyncpg.Connection[Any]) -> set[str]:
    rows = await connection.fetch(
        """
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        """,
        SCHEMA_NAME,
    )
    return {str(row["relname"]) for row in rows}


async def reset_postgres(
    connection: asyncpg.Connection[Any], table_specs: Sequence[TableSpec], confirm_reset: bool
) -> None:
    expected = {spec.name for spec in table_specs} | {spec.view_name for spec in table_specs}
    existing = await existing_seed_objects(connection)
    unexpected = sorted(existing - expected)
    if unexpected:
        raise RuntimeError(
            f"Refusing reset: {SCHEMA_NAME} contains non-seed objects: {', '.join(unexpected[:10])}."
        )
    if existing and not confirm_reset:
        raise RuntimeError(
            "Existing semiconductor seed objects found. Re-run with --confirm-reset to replace them."
        )
    if not existing:
        return
    print(f"Resetting {len(existing)} existing objects in {SCHEMA_NAME}...")
    for completed, spec in enumerate(reversed(table_specs), start=1):
        await connection.execute(
            f"DROP VIEW IF EXISTS {quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.view_name)} CASCADE"
        )
        if completed % DEFAULT_BATCH_SIZE == 0 or completed == len(table_specs):
            print(f"Progress: {completed}/{len(table_specs)} views dropped")
    for completed, spec in enumerate(reversed(table_specs), start=1):
        await connection.execute(
            f"DROP TABLE IF EXISTS {quote_identifier(SCHEMA_NAME)}.{quote_identifier(spec.name)} CASCADE"
        )
        if completed % DEFAULT_BATCH_SIZE == 0 or completed == len(table_specs):
            print(f"Progress: {completed}/{len(table_specs)} tables dropped")


async def apply_postgres(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    table_specs: Sequence[TableSpec],
    rows_per_table: int,
    confirm_reset: bool,
) -> None:
    connection = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        command_timeout=45,
    )
    try:
        await connection.execute(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(SCHEMA_NAME)}")
        await reset_postgres(connection, table_specs, confirm_reset)
        created_tables = 0
        for family in FAMILIES:
            family_tables = [table for table in table_specs if table.family.slug == family.slug]
            async with connection.transaction():
                for table in family_tables:
                    await connection.execute(create_table_sql(table))
                    await connection.executemany(
                        insert_sql(table),
                        [
                            row_values(table, row_number, rows_per_table)
                            for row_number in range(1, rows_per_table + 1)
                        ],
                    )
                    created_tables += 1
                    if created_tables % DEFAULT_BATCH_SIZE == 0 or created_tables == len(
                        table_specs
                    ):
                        print(f"Progress: {created_tables}/{len(table_specs)} tables created")
        created_views = 0
        for family in FAMILIES:
            family_tables = [table for table in table_specs if table.family.slug == family.slug]
            async with connection.transaction():
                for table in family_tables:
                    await connection.execute(create_view_sql(table))
                    created_views += 1
                    if created_views % DEFAULT_BATCH_SIZE == 0 or created_views == len(table_specs):
                        print(f"Progress: {created_views}/{len(table_specs)} views created")
    finally:
        await connection.close()


def entity_family_and_scenario(entity: EntitySpec) -> tuple[Family, str]:
    """Resolve deterministic family/scenario without trusting a provider URN."""
    object_name = entity.name.removeprefix("vw_")
    for family in FAMILIES:
        prefix = f"{family.slug}_"
        if not object_name.startswith(prefix):
            continue
        scenario = object_name.removeprefix(prefix)
        if scenario in SCENARIOS:
            return family, scenario
    raise AssertionError(f"Generated entity has no semiconductor taxonomy mapping: {entity.name}")


def datahub_entity_governance(entity: EntitySpec) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return deterministic dataset-level (term URNs, tag URNs)."""
    family, scenario = entity_family_and_scenario(entity)
    _, stage_id, _ = STAGE_FOR_FAMILY[family.slug]
    term_urns = (
        f"urn:li:glossaryTerm:{family.slug}",
        "urn:li:glossaryTerm:semiconductor_scenario",
    )
    tag_ids = (
        "datariver_semiconductor",
        "datariver_seed",
        "datariver_synthetic",
        f"datariver_value_chain_{stage_id}",
        f"datariver_object_{entity.kind}",
        f"datariver_execution_{entity.execution_mode.casefold()}",
        f"datariver_platform_{entity.platform}",
        f"datariver_scenario_{scenario}",
    )
    return term_urns, tuple(f"urn:li:tag:{tag_id}" for tag_id in tag_ids)


def datahub_field_governance(field_path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return controlled field semantics for the common deterministic schema."""
    semantic = FIELD_SEMANTICS.get(field_path)
    if semantic is not None:
        term_id, tag_suffix = semantic
        return (f"urn:li:glossaryTerm:{term_id}",), (f"urn:li:tag:datariver_field_{tag_suffix}",)
    if field_path.startswith("parent_") and field_path.endswith("_name"):
        return ("urn:li:glossaryTerm:referenced_record",), ("urn:li:tag:datariver_field_reference",)
    if field_path.endswith("_id"):
        parent_name = field_path.removesuffix("_id")
        for family in FAMILIES:
            if parent_name.startswith(f"{family.slug}_"):
                return (f"urn:li:glossaryTerm:{family.slug}",), (
                    "urn:li:tag:datariver_field_reference",
                )
    # This assertion turns an unclassified newly added field into a deliberate
    # taxonomy update, rather than silently emitting an ungoverned column.
    raise AssertionError(f"Generated field has no semiconductor taxonomy mapping: {field_path}")


def datahub_glossary_terms_document(terms: Sequence[str]) -> dict[str, Any]:
    """Build the REST-aspect shape (not the GraphQL ``term`` presentation)."""
    return {
        "terms": [{"urn": term} for term in terms],
        "auditStamp": {"time": 0, "actor": DATAHUB_SYSTEM_ACTOR},
    }


def datahub_schema_fields(spec: EntitySpec) -> list[dict[str, Any]]:
    field_names: tuple[tuple[str, str, bool], ...]
    if spec.kind == "view":
        field_names = (
            ("id", "uuid", False),
            ("business_key", "text", False),
            ("record_name", "text", False),
            ("scenario_code", "text", False),
            ("lifecycle_status", "text", False),
            ("operational_region", "text", False),
            ("annual_volume", "integer", False),
            ("unit_cost", "numeric(14,2)", False),
            ("effective_date", "date", False),
        )
    else:
        # The exact physical field shape remains deterministic and has no user data.
        matching_table = next(
            table for table in build_table_specs() if table.qualified_name == spec.qualified_name
        )
        field_names = tuple(
            (name, data_type, "NOT NULL" in constraint)
            for name, data_type, constraint in common_columns(matching_table)
        )
    type_map = {
        "integer": "com.linkedin.schema.NumberType",
        "numeric(14,2)": "com.linkedin.schema.NumberType",
        "boolean": "com.linkedin.schema.BooleanType",
        "uuid": "com.linkedin.schema.StringType",
        "text": "com.linkedin.schema.StringType",
        "date": "com.linkedin.schema.StringType",
        "timestamptz": "com.linkedin.schema.StringType",
    }
    fields: list[dict[str, Any]] = []
    for name, data_type, not_null in field_names:
        terms, tags = datahub_field_governance(name)
        fields.append(
            {
                "fieldPath": name,
                "type": {"type": {type_map[data_type]: {}}},
                "nativeDataType": data_type,
                "description": f"Synthetic {name.replace('_', ' ')} field for local lineage testing.",
                "nullable": not not_null,
                "isPartOfKey": name == "id",
                "globalTags": {"tags": [{"tag": tag} for tag in tags]},
                "glossaryTerms": datahub_glossary_terms_document(terms),
            }
        )
    return fields


def canonical_hash(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def aspect_documents(entity: EntitySpec, run_id: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    platform_urn = f"urn:li:dataPlatform:{entity.platform}"
    schema_fields = datahub_schema_fields(entity)
    glossary_terms, tags = datahub_entity_governance(entity)
    schema_document = {
        "schemaName": entity.qualified_name,
        "platform": platform_urn,
        "version": 0,
        "hash": canonical_hash({"fields": schema_fields, "name": entity.qualified_name}),
        "platformSchema": {"com.linkedin.schema.OtherSchema": {"rawSchema": entity.qualified_name}},
        "fields": schema_fields,
    }
    properties_document = {
        "name": entity.name,
        "description": entity.description,
        "customProperties": {
            "datariver.seed.id": "semiconductor-value-chain-v1",
            "datariver.seed.run_id": run_id,
            "datariver.seed.execution_mode": entity.execution_mode,
            "datariver.seed.object_kind": entity.kind,
            "datariver.seed.database_name": entity.database_name,
        },
    }
    upstreams = [
        {
            "dataset": (
                f"urn:li:dataset:(urn:li:dataPlatform:{entity.platform},{upstream},{ENVIRONMENT})"
            ),
            "type": "TRANSFORMED",
        }
        for upstream in entity.upstream_qualified_names
    ]
    lineage_document = {"upstreams": upstreams, "fineGrainedLineages": []}
    documents: list[tuple[str, dict[str, Any]]] = [
        ("datasetProperties", properties_document),
        ("globalTags", {"tags": [{"tag": tag} for tag in tags]}),
        ("glossaryTerms", datahub_glossary_terms_document(glossary_terms)),
    ]
    # Every generated dataset carries the same explicit field contract.  Oracle
    # is still clearly labelled MOCK, but omitting its schema aspect made its
    # column descriptions, Tag and Term semantics disappear in DataHub-backed
    # catalog, registration and change-management views.
    documents.append(("schemaMetadata", schema_document))
    documents.append(("upstreamLineage", lineage_document))
    return tuple(documents)


async def post_metadata_aspect(
    client: httpx.AsyncClient,
    *,
    entity_type: str,
    entity_urn: str,
    entity_label: str,
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    proposal = {
        "proposal": {
            "entityType": entity_type,
            "entityUrn": entity_urn,
            "changeType": "UPSERT",
            "aspectName": aspect_name,
            "aspect": {
                # DataHub's REST proposal wrapper does not consistently honour
                # a UTF-8 charset for the embedded JSON string.  Escaping
                # non-ASCII keeps Korean/typographic glossary and tag labels
                # lossless across the v1.6 endpoint.
                "value": json.dumps(document, ensure_ascii=True, separators=(",", ":")),
                "contentType": "application/json",
            },
        }
    }
    for attempt in range(1, 6):
        try:
            response = await client.post(
                "/aspects?action=ingestProposal",
                json=proposal,
                headers={"Idempotency-Key": canonical_hash(proposal)},
            )
        except httpx.TransportError as error:
            if attempt == 5:
                raise RuntimeError(
                    f"DataHub transport failure for {entity_label} {aspect_name}: "
                    f"{type(error).__name__}."
                ) from error
            await asyncio.sleep(float(attempt))
            continue
        if response.status_code < 400:
            return
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == 5:
            detail = response.text.replace("\n", " ")[:500]
            raise RuntimeError(
                f"DataHub rejected {entity_label} {aspect_name}: "
                f"HTTP {response.status_code}; {detail}"
            )
        await asyncio.sleep(float(attempt))


async def post_aspect(
    client: httpx.AsyncClient,
    *,
    entity: EntitySpec,
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    await post_metadata_aspect(
        client,
        entity_type="dataset",
        entity_urn=entity.urn,
        entity_label=entity.qualified_name,
        aspect_name=aspect_name,
        document=document,
    )


def governance_aspect_documents(
    taxonomy: DataHubGovernanceTaxonomy,
) -> tuple[tuple[str, str, str, str, dict[str, Any]], ...]:
    """Return typed DataHub vocabulary aspects in parent-before-child order."""
    documents: list[tuple[str, str, str, str, dict[str, Any]]] = []
    for node in taxonomy.nodes:
        document: dict[str, Any] = {"name": node.name, "definition": node.definition}
        if node.parent_node_id is not None:
            document["parentNode"] = f"urn:li:glossaryNode:{node.parent_node_id}"
        documents.append(("glossaryNode", node.urn, node.name, "glossaryNodeInfo", document))
    for term in taxonomy.terms:
        documents.append(
            (
                "glossaryTerm",
                term.urn,
                term.name,
                "glossaryTermInfo",
                {
                    "name": term.name,
                    "definition": term.definition,
                    "termSource": "INTERNAL",
                    "parentNode": f"urn:li:glossaryNode:{term.parent_node_id}",
                },
            )
        )
    for tag in taxonomy.tags:
        documents.append(
            (
                "tag",
                tag.urn,
                tag.name,
                "tagProperties",
                {"name": tag.name, "description": tag.description},
            )
        )
    return tuple(documents)


async def seed_datahub_governance(
    client: httpx.AsyncClient, *, taxonomy: DataHubGovernanceTaxonomy
) -> None:
    documents = governance_aspect_documents(taxonomy)
    for position, (entity_type, entity_urn, label, aspect_name, document) in enumerate(
        documents, start=1
    ):
        await post_metadata_aspect(
            client,
            entity_type=entity_type,
            entity_urn=entity_urn,
            entity_label=label,
            aspect_name=aspect_name,
            document=document,
        )
        print(f"Progress: {position}/{len(documents)} DataHub governance entities seeded")


async def seed_and_verify_datahub_governance(*, datahub_url: str, token: str) -> dict[str, int]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    taxonomy = datahub_governance_taxonomy()
    async with httpx.AsyncClient(
        base_url=datahub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(90.0)
    ) as client:
        config_response = await client.get("/config")
        config_response.raise_for_status()
        await seed_datahub_governance(client, taxonomy=taxonomy)
        return await verify_datahub_governance(client, taxonomy=taxonomy)


def _aspect_document(payload: object) -> dict[str, Any]:
    envelope = payload.get("aspect", payload) if isinstance(payload, dict) else payload
    value = envelope.get("value", envelope) if isinstance(envelope, dict) else envelope
    # The reviewed DataHub REST endpoint may return either an Aspect envelope
    # with ``value`` or the legacy fully-qualified aspect-name wrapper.
    if isinstance(value, dict) and len(value) == 1 and isinstance(next(iter(value.values())), dict):
        value = next(iter(value.values()))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise RuntimeError("DataHub returned an invalid aspect JSON envelope.") from error
    if not isinstance(value, dict):
        raise RuntimeError("DataHub returned an invalid aspect envelope.")
    return value


async def read_datahub_aspect(
    client: httpx.AsyncClient, *, entity_urn: str, aspect_name: str
) -> dict[str, Any]:
    response = await client.get(
        f"/aspects/{quote(entity_urn, safe='')}",
        params={"aspect": aspect_name, "version": "0"},
    )
    if response.status_code >= 400:
        detail = response.text.replace("\n", " ")[:500]
        raise RuntimeError(
            f"DataHub verification read failed for {entity_urn} {aspect_name}: "
            f"HTTP {response.status_code}; {detail}"
        )
    try:
        return _aspect_document(response.json())
    except ValueError as error:
        raise RuntimeError(
            f"DataHub returned invalid JSON while verifying {entity_urn} {aspect_name}."
        ) from error


def _aspect_references(document: dict[str, Any], *, field: str, nested: str) -> set[str]:
    references: set[str] = set()
    raw_items = document.get(field)
    for item in raw_items if isinstance(raw_items, list) else []:
        value = item.get(nested) if isinstance(item, dict) else None
        if value is None and nested == "urn" and isinstance(item, dict):
            # GraphQL enrichment represents a term as ``term`` while the
            # REST aspect requires ``urn``. Accept both only for read-back.
            value = item.get("term")
        if isinstance(value, dict):
            value = value.get("urn")
        if isinstance(value, str):
            references.add(value)
    return references


async def verify_datahub_governance(
    client: httpx.AsyncClient, *, taxonomy: DataHubGovernanceTaxonomy
) -> dict[str, int]:
    for node in taxonomy.nodes:
        document = await read_datahub_aspect(
            client, entity_urn=node.urn, aspect_name="glossaryNodeInfo"
        )
        if document.get("name") != node.name:
            raise RuntimeError(f"DataHub glossary node verification failed: {node.urn}")
        expected_parent = (
            None if node.parent_node_id is None else f"urn:li:glossaryNode:{node.parent_node_id}"
        )
        if document.get("parentNode") != expected_parent:
            raise RuntimeError(f"DataHub glossary node parent verification failed: {node.urn}")
    for term in taxonomy.terms:
        document = await read_datahub_aspect(
            client, entity_urn=term.urn, aspect_name="glossaryTermInfo"
        )
        if (
            document.get("name") != term.name
            or document.get("parentNode") != f"urn:li:glossaryNode:{term.parent_node_id}"
        ):
            raise RuntimeError(f"DataHub glossary term verification failed: {term.urn}")
    for tag in taxonomy.tags:
        document = await read_datahub_aspect(
            client, entity_urn=tag.urn, aspect_name="tagProperties"
        )
        if document.get("name") != tag.name:
            raise RuntimeError(f"DataHub tag verification failed: {tag.urn}")
    return {"nodes": len(taxonomy.nodes), "terms": len(taxonomy.terms), "tags": len(taxonomy.tags)}


async def ingest_datahub(
    *,
    entities: Sequence[EntitySpec],
    datahub_url: str,
    token: str,
    batch_size: int,
    run_id: str,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(
        base_url=datahub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(90.0)
    ) as client:
        config_response = await client.get("/config")
        config_response.raise_for_status()
        await seed_datahub_governance(client, taxonomy=datahub_governance_taxonomy())
        for offset in range(0, len(entities), batch_size):
            batch = entities[offset : offset + batch_size]

            async def ingest_entity(entity: EntitySpec) -> None:
                for aspect_name, document in aspect_documents(entity, run_id):
                    await post_aspect(
                        client,
                        entity=entity,
                        aspect_name=aspect_name,
                        document=document,
                    )

            await asyncio.gather(*(ingest_entity(entity) for entity in batch))
            print(
                f"Progress: {min(offset + len(batch), len(entities))}/{len(entities)} DataHub entities ingested"
            )
            if on_progress is not None:
                on_progress(min(offset + len(batch), len(entities)))


async def verify_datahub_entities(
    *,
    entities: Sequence[EntitySpec],
    datahub_url: str,
    token: str,
    batch_size: int,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    found = 0
    async with httpx.AsyncClient(
        base_url=datahub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(30.0)
    ) as client:
        await verify_datahub_governance(client, taxonomy=datahub_governance_taxonomy())
        for offset in range(0, len(entities), batch_size):
            batch = entities[offset : offset + batch_size]

            async def verify(entity: EntitySpec) -> bool:
                properties = await read_datahub_aspect(
                    client, entity_urn=entity.urn, aspect_name="datasetProperties"
                )
                if not isinstance(properties.get("name"), str):
                    return False
                expected_terms, expected_tags = datahub_entity_governance(entity)
                tags = await read_datahub_aspect(
                    client, entity_urn=entity.urn, aspect_name="globalTags"
                )
                terms = await read_datahub_aspect(
                    client, entity_urn=entity.urn, aspect_name="glossaryTerms"
                )
                if not set(expected_tags).issubset(
                    _aspect_references(tags, field="tags", nested="tag")
                ) or not set(expected_terms).issubset(
                    _aspect_references(terms, field="terms", nested="urn")
                ):
                    return False
                schema = await read_datahub_aspect(
                    client, entity_urn=entity.urn, aspect_name="schemaMetadata"
                )
                fields = schema.get("fields")
                if not isinstance(fields, list):
                    return False
                by_path = {
                    item.get("fieldPath"): item
                    for item in fields
                    if isinstance(item, dict) and isinstance(item.get("fieldPath"), str)
                }
                for field_path in datahub_schema_fields(entity):
                    name = field_path["fieldPath"]
                    actual = by_path.get(name)
                    if not isinstance(actual, dict):
                        return False
                    field_terms, field_tags = datahub_field_governance(name)
                    global_tags = actual.get("globalTags")
                    glossary_terms = actual.get("glossaryTerms")
                    if not isinstance(global_tags, dict) or not isinstance(glossary_terms, dict):
                        return False
                    if not set(field_tags).issubset(
                        _aspect_references(global_tags, field="tags", nested="tag")
                    ) or not set(field_terms).issubset(
                        _aspect_references(glossary_terms, field="terms", nested="urn")
                    ):
                        return False
                return True

            found += sum(await asyncio.gather(*(verify(entity) for entity in batch)))
            print(
                f"Progress: {min(offset + len(batch), len(entities))}/{len(entities)} DataHub entities verified"
            )
            if on_progress is not None:
                on_progress(min(offset + len(batch), len(entities)))
    if found != len(entities):
        raise RuntimeError(
            f"DataHub verification found {found}/{len(entities)} generated entities."
        )
    return found


def read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"Required secret file is unavailable: {path}") from error
    if not value:
        raise RuntimeError(f"Required secret file is empty: {path}")
    return value


def parse_rows(value: str) -> int:
    try:
        rows = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("rows per table must be an integer") from error
    if not 10 <= rows <= 50:
        raise argparse.ArgumentTypeError("rows per table must be between 10 and 50")
    return rows


def parse_positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("batch size must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("batch size must be positive")
    return parsed


def parse_nonnegative(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("offset must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Create the PostgreSQL seed schema and rows."
    )
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Allow removal of a previous deterministic semiconductor seed before rebuilding.",
    )
    parser.add_argument(
        "--ingest-datahub",
        action="store_true",
        help="Seed controlled vocabulary, enrich generated metadata, and emit lineage to DataHub.",
    )
    parser.add_argument(
        "--seed-governance",
        action="store_true",
        help="Seed and verify only the controlled semiconductor glossary and tag vocabulary.",
    )
    parser.add_argument(
        "--verify-datahub",
        action="store_true",
        help="Read generated dataset properties without emitting new DataHub proposals.",
    )
    parser.add_argument(
        "--entity-scope",
        choices=("postgres", "dual"),
        default="dual",
        help="DataHub entity scope; dual includes explicitly labelled Oracle MOCK metadata.",
    )
    parser.add_argument("--rows-per-table", type=parse_rows, default=DEFAULT_ROWS_PER_TABLE)
    parser.add_argument(
        "--datahub-batch-size", type=parse_positive, default=DEFAULT_DATAHUB_BATCH_SIZE
    )
    parser.add_argument(
        "--max-datahub-entities",
        type=parse_positive,
        help="Bounded diagnostic run; omit to ingest every entity in the selected scope.",
    )
    parser.add_argument(
        "--datahub-start-index",
        type=parse_nonnegative,
        default=0,
        help="Resume a bounded DataHub emission range without reprocessing earlier entities.",
    )
    parser.add_argument(
        "--postgres-host", default=os.getenv("SEMICONDUCTOR_POSTGRES_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--postgres-port", type=int, default=int(os.getenv("SEMICONDUCTOR_POSTGRES_PORT", "5432"))
    )
    parser.add_argument(
        "--postgres-database", default=os.getenv("SEMICONDUCTOR_POSTGRES_DATABASE", "datariver")
    )
    parser.add_argument(
        "--oracle-database",
        default=os.getenv("SEMICONDUCTOR_ORACLE_DATABASE", "ORCL"),
        help="DataHub database label for the separately configured Oracle seed metadata.",
    )
    parser.add_argument(
        "--postgres-user", default=os.getenv("SEMICONDUCTOR_POSTGRES_USER", "datariver_owner")
    )
    parser.add_argument(
        "--postgres-password-file",
        type=Path,
        default=Path(
            os.getenv("SEMICONDUCTOR_POSTGRES_PASSWORD_FILE", "secrets/postgres_password")
        ),
    )
    parser.add_argument(
        "--datahub-url", default=os.getenv("DATAHUB_BASE_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument(
        "--datahub-token-file",
        type=Path,
        default=Path(os.getenv("DATAHUB_TOKEN_FILE", "secrets/datahub_token")),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/semiconductor-seed"),
        help="Ignored runtime output directory.",
    )
    return parser


async def async_main(arguments: argparse.Namespace) -> int:
    table_specs = build_table_specs()
    entities = build_entities(
        table_specs,
        arguments.entity_scope,
        postgres_database_name=arguments.postgres_database,
        oracle_database_name=arguments.oracle_database,
    )
    if len(table_specs) != 500 or len(entities) not in {1000, 2000}:
        raise AssertionError("Unexpected deterministic semiconductor seed cardinality.")
    selected_entities = entities[arguments.datahub_start_index :]
    if arguments.max_datahub_entities is not None:
        selected_entities = selected_entities[: arguments.max_datahub_entities]
    run_id = canonical_hash(
        {
            "families": [asdict(family) for family in FAMILIES],
            "scenarios": SCENARIOS,
            "rows_per_table": arguments.rows_per_table,
            "entity_scope": arguments.entity_scope,
        }
    )[:20]
    output_directory = arguments.output_dir
    write_oracle_mock(output_directory, table_specs)
    manifest_path = output_directory / "manifest.json"
    prior_postgres = previous_postgres_state(manifest_path)
    manifest: dict[str, Any] = {
        "seed_id": "semiconductor-value-chain-v1",
        "run_id": run_id,
        "generated_at": datetime.now(UTC),
        "schema": SCHEMA_NAME,
        "postgres": {
            "tables": len(table_specs),
            "views": len(table_specs),
            "applied": bool(prior_postgres.get("applied", False)),
            "rows_per_table": prior_postgres.get("rows_per_table"),
        },
        "oracle": {"tables": len(table_specs), "views": len(table_specs), "execution_mode": "MOCK"},
        "datahub": {
            "entities_requested": len(selected_entities),
            "entities_ingested": 0,
            "entities_verified": 0,
            "start_index": arguments.datahub_start_index,
            "phase": "PLANNED",
            "governance": {
                "nodes_expected": len(datahub_governance_taxonomy().nodes),
                "terms_expected": len(datahub_governance_taxonomy().terms),
                "tags_expected": len(datahub_governance_taxonomy().tags),
                "verified": False,
            },
        },
    }
    write_json(manifest_path, manifest)
    print(
        f"Plan: {len(table_specs)} PostgreSQL tables, {len(table_specs)} PostgreSQL views, "
        f"{len(selected_entities)} DataHub entities ({arguments.entity_scope})."
    )
    if arguments.apply:
        await apply_postgres(
            host=arguments.postgres_host,
            port=arguments.postgres_port,
            database=arguments.postgres_database,
            user=arguments.postgres_user,
            password=read_secret(arguments.postgres_password_file),
            table_specs=table_specs,
            rows_per_table=arguments.rows_per_table,
            confirm_reset=arguments.confirm_reset,
        )
        manifest["postgres"]["applied"] = True
        manifest["postgres"]["rows_per_table"] = arguments.rows_per_table
        write_json(manifest_path, manifest)
    if arguments.ingest_datahub:
        token = read_secret(arguments.datahub_token_file)

        def record_ingest_progress(completed: int) -> None:
            manifest["datahub"]["phase"] = "INGESTING"
            manifest["datahub"]["entities_ingested"] = completed
            write_json(manifest_path, manifest)

        await ingest_datahub(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
            run_id=run_id,
            on_progress=record_ingest_progress,
        )

        def record_verify_progress(completed: int) -> None:
            manifest["datahub"]["phase"] = "VERIFYING"
            manifest["datahub"]["entities_verified"] = completed
            write_json(manifest_path, manifest)

        manifest["datahub"]["entities_verified"] = await verify_datahub_entities(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
            on_progress=record_verify_progress,
        )
        manifest["datahub"]["governance"]["verified"] = True
        manifest["datahub"]["phase"] = "COMPLETE"
        write_json(manifest_path, manifest)
    elif arguments.seed_governance:
        token = read_secret(arguments.datahub_token_file)
        verified_governance = await seed_and_verify_datahub_governance(
            datahub_url=arguments.datahub_url,
            token=token,
        )
        manifest["datahub"]["governance"] = {
            "nodes_expected": len(datahub_governance_taxonomy().nodes),
            "terms_expected": len(datahub_governance_taxonomy().terms),
            "tags_expected": len(datahub_governance_taxonomy().tags),
            "nodes_verified": verified_governance["nodes"],
            "terms_verified": verified_governance["terms"],
            "tags_verified": verified_governance["tags"],
            "verified": True,
        }
        write_json(manifest_path, manifest)
    elif arguments.verify_datahub:
        token = read_secret(arguments.datahub_token_file)

        def record_verify_progress(completed: int) -> None:
            manifest["datahub"]["phase"] = "VERIFYING"
            manifest["datahub"]["entities_verified"] = completed
            write_json(manifest_path, manifest)

        manifest["datahub"]["entities_verified"] = await verify_datahub_entities(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
            on_progress=record_verify_progress,
        )
        manifest["datahub"]["governance"]["verified"] = True
        manifest["datahub"]["phase"] = "COMPLETE"
        write_json(manifest_path, manifest)
    print(f"Manifest: {manifest_path}")
    return 0


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        return asyncio.run(async_main(arguments))
    except (RuntimeError, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
