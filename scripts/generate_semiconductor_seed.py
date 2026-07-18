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
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import asyncpg
import httpx

SCHEMA_NAME = "semiconductor_seed"
ENVIRONMENT = "DEV"
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
    table_specs: Sequence[TableSpec], scope: Literal["postgres", "dual"]
) -> tuple[EntitySpec, ...]:
    platforms: tuple[Literal["postgres", "oracle"], ...] = (
        ("postgres", "oracle") if scope == "dual" else ("postgres",)
    )
    entities: list[EntitySpec] = []
    for platform in platforms:
        execution_mode: Literal["APPLIED", "MOCK"] = "APPLIED" if platform == "postgres" else "MOCK"
        for table in table_specs:
            entities.append(
                EntitySpec(
                    platform=platform,
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


def datahub_schema_fields(spec: EntitySpec) -> list[dict[str, Any]]:
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
    return [
        {
            "fieldPath": name,
            "type": {"type": {type_map[data_type]: {}}},
            "nativeDataType": data_type,
            "description": f"Synthetic {name.replace('_', ' ')} field for local lineage testing.",
            "nullable": not not_null,
            "isPartOfKey": name == "id",
        }
        for name, data_type, not_null in field_names
    ]


def canonical_hash(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def aspect_documents(entity: EntitySpec, run_id: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    platform_urn = f"urn:li:dataPlatform:{entity.platform}"
    schema_fields = datahub_schema_fields(entity)
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
    documents: list[tuple[str, dict[str, Any]]] = [("datasetProperties", properties_document)]
    # PostgreSQL tables are the real profiled source.  Views and Oracle MOCK
    # entities retain their explicit lineage and the generated DDL manifest,
    # without multiplying local GMS schema-index work unnecessarily.
    if entity.platform == "postgres" and entity.kind == "table":
        documents.append(("schemaMetadata", schema_document))
    documents.append(("upstreamLineage", lineage_document))
    return tuple(documents)


async def post_aspect(
    client: httpx.AsyncClient,
    *,
    entity: EntitySpec,
    aspect_name: str,
    document: dict[str, Any],
) -> None:
    proposal = {
        "proposal": {
            "entityType": "dataset",
            "entityUrn": entity.urn,
            "changeType": "UPSERT",
            "aspectName": aspect_name,
            "aspect": {
                "value": json.dumps(document, ensure_ascii=False, separators=(",", ":")),
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
                    f"DataHub transport failure for {entity.qualified_name} {aspect_name}: "
                    f"{type(error).__name__}."
                ) from error
            await asyncio.sleep(float(attempt))
            continue
        if response.status_code < 400:
            return
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == 5:
            detail = response.text.replace("\n", " ")[:500]
            raise RuntimeError(
                f"DataHub rejected {entity.qualified_name} {aspect_name}: "
                f"HTTP {response.status_code}; {detail}"
            )
        await asyncio.sleep(float(attempt))


async def ingest_datahub(
    *, entities: Sequence[EntitySpec], datahub_url: str, token: str, batch_size: int, run_id: str
) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(
        base_url=datahub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(90.0)
    ) as client:
        config_response = await client.get("/config")
        config_response.raise_for_status()
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


async def verify_datahub_entities(
    *, entities: Sequence[EntitySpec], datahub_url: str, token: str, batch_size: int
) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    found = 0
    async with httpx.AsyncClient(
        base_url=datahub_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(30.0)
    ) as client:
        for offset in range(0, len(entities), batch_size):
            batch = entities[offset : offset + batch_size]

            async def verify(entity: EntitySpec) -> bool:
                response = await client.get(
                    f"/aspects/{quote(entity.urn, safe='')}",
                    params={"aspect": "datasetProperties", "version": "0"},
                )
                return response.status_code < 400

            found += sum(await asyncio.gather(*(verify(entity) for entity in batch)))
            print(
                f"Progress: {min(offset + len(batch), len(entities))}/{len(entities)} DataHub entities verified"
            )
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
        help="Emit generated metadata and lineage to DataHub.",
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
    entities = build_entities(table_specs, arguments.entity_scope)
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
            "entities_verified": 0,
            "start_index": arguments.datahub_start_index,
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
        await ingest_datahub(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
            run_id=run_id,
        )
        manifest["datahub"]["entities_verified"] = await verify_datahub_entities(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
        )
        write_json(manifest_path, manifest)
    elif arguments.verify_datahub:
        token = read_secret(arguments.datahub_token_file)
        manifest["datahub"]["entities_verified"] = await verify_datahub_entities(
            entities=selected_entities,
            datahub_url=arguments.datahub_url,
            token=token,
            batch_size=arguments.datahub_batch_size,
        )
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
