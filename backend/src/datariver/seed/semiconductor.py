from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from datariver.domain.knowledge import GraphEdge, GraphNode, GraphSnapshot, Provenance

SEED_NAMESPACE = "datariver.seed.semiconductor"
PACK_VERSION = "1.0.0"
UUID_NAMESPACE = UUID("b4fa65dd-8f4c-4f7c-a441-454cf9ca2c41")

STAGES = (
    ("ip-eda", "IP & EDA"),
    ("materials", "Materials"),
    ("equipment", "Equipment"),
    ("design", "Fabless Design"),
    ("wafer", "Wafer Manufacturing"),
    ("fabrication", "Wafer Fabrication"),
    ("osat", "Assembly & Test"),
    ("distribution", "Distribution"),
    ("end-market", "End Market"),
)
FACILITIES = (
    ("fab-north", "Synthetic Fab North", "East Asia", 100_000),
    ("fab-west", "Synthetic Fab West", "North America", 72_000),
    ("fab-central", "Synthetic Fab Central", "Europe", 48_000),
    ("osat-south", "Synthetic OSAT South", "Southeast Asia", 140_000),
    ("materials-east", "Synthetic Materials East", "East Asia", 85_000),
    ("equipment-hub", "Synthetic Equipment Hub", "Europe", 36_000),
)
MATERIALS = (
    "Electronic-grade silicon",
    "EUV photoresist",
    "Argon process gas",
    "Neon excimer gas",
    "Copper target",
    "Tungsten precursor",
    "High-k dielectric precursor",
    "CMP slurry",
    "Ultra-pure water",
    "Advanced package substrate",
)
EQUIPMENT = (
    "EUV lithography",
    "DUV lithography",
    "Plasma etch",
    "Atomic layer deposition",
    "Chemical vapor deposition",
    "Ion implantation",
    "CMP polishing",
    "Defect metrology",
)
PROCESSES = (
    "Crystal growth",
    "Wafer slicing",
    "Thermal oxidation",
    "Photoresist coating",
    "Lithography exposure",
    "Pattern etch",
    "Ion implantation",
    "Thin-film deposition",
    "Chemical mechanical planarization",
    "Wafer probe",
    "Advanced packaging",
    "Final test",
)
PRODUCTS = (
    "Logic compute die",
    "Memory die",
    "Power semiconductor",
    "Analog mixed-signal IC",
    "Image sensor",
    "Chiplet package",
    "Automotive module",
    "AI accelerator board",
)
RISKS = (
    "Single-source material",
    "Equipment lead-time",
    "Regional logistics disruption",
    "Export-control restriction",
    "Utility capacity constraint",
    "Yield excursion",
)
PERIODS = tuple(f"2026-{month:02d}" for month in range(1, 13))


@dataclass(frozen=True, slots=True)
class CatalogSeed:
    key: str
    name: str
    description: str
    platform: str
    classification: int


@dataclass(frozen=True, slots=True)
class SemiconductorPack:
    snapshot: GraphSnapshot
    catalog_assets: tuple[CatalogSeed, ...]
    logical_hash: str


def stable_id(value: str) -> UUID:
    return uuid5(UUID_NAMESPACE, value)


def build_pack() -> SemiconductorPack:
    catalog_assets = _load_catalog_assets()
    provenance = (
        Provenance(
            source_ref="seed:semiconductor:v1",
            source_locator="seed/semiconductor/manifest.yaml",
            source_version=PACK_VERSION,
            method="SYNTHETIC_TEMPLATE",
            confidence=1.0,
        ),
    )
    nodes: dict[UUID, GraphNode] = {}
    references: dict[str, UUID] = {}

    def add_node(
        entity_type: str,
        key: str,
        name: str,
        *,
        classification: int = 1,
        properties: dict[str, Any] | None = None,
    ) -> UUID:
        entity_id = stable_id(f"node:{entity_type}:{key}")
        references[f"{entity_type}:{key}"] = entity_id
        nodes[entity_id] = GraphNode(
            entity_id=entity_id,
            entity_type=entity_type,
            properties={
                "name": name,
                "seed_namespace": SEED_NAMESPACE,
                "pack_version": PACK_VERSION,
                "is_synthetic": True,
                **(properties or {}),
            },
            classification=classification,
            provenance=provenance,
        )
        return entity_id

    for index, (key, name) in enumerate(STAGES):
        add_node("ValueChainStage", key, name, properties={"sequence": index + 1})
        for company_index in range(2):
            add_node(
                "Company",
                f"{key}-{company_index + 1}",
                f"Synthetic {name} Company {company_index + 1}",
                properties={
                    "stage_key": key,
                    "synthetic_market_share_pct": 8 + index * 2 + company_index * 3,
                },
            )
    for key, name, region, capacity in FACILITIES:
        add_node(
            "Facility",
            key,
            name,
            properties={
                "region": region,
                "synthetic_monthly_capacity_units": capacity,
                "synthetic_utilization_pct": 78 + capacity % 13,
            },
        )
    for index, name in enumerate(MATERIALS):
        add_node(
            "Material",
            f"material-{index + 1}",
            name,
            properties={
                "synthetic_lead_time_days": 21 + index * 7,
                "synthetic_qualified_source_count": 1 + index % 4,
            },
        )
    for index, name in enumerate(EQUIPMENT):
        add_node(
            "EquipmentFamily",
            f"equipment-{index + 1}",
            name,
            properties={"synthetic_lead_time_days": 120 + index * 45},
        )
    for index, name in enumerate(PROCESSES):
        add_node(
            "ProcessStep",
            f"process-{index + 1}",
            name,
            properties={"sequence": index + 1, "synthetic_cycle_time_hours": 4 + index * 2},
        )
    for index, name in enumerate(PRODUCTS):
        add_node(
            "Product",
            f"product-{index + 1}",
            name,
            classification=2 if index in {0, 1, 7} else 1,
            properties={"synthetic_demand_index": 100 + index * 13},
        )
    for index, name in enumerate(RISKS):
        add_node(
            "RiskFactor",
            f"risk-{index + 1}",
            name,
            properties={
                "synthetic_probability": round(0.08 + index * 0.07, 2),
                "synthetic_impact_score": 55 + index * 7,
            },
        )
    for facility_index, (key, name, _region, capacity) in enumerate(FACILITIES):
        for period_index, period in enumerate(PERIODS):
            utilization_pct = 72 + ((facility_index * 7 + period_index * 3) % 24)
            yield_pct = 88 + ((facility_index * 3 + period_index) % 9)
            utilized_units = capacity * utilization_pct // 100
            add_node(
                "MetricObservation",
                f"facility-{key}-{period}",
                f"{name} capacity observation {period}",
                properties={
                    "subject_type": "Facility",
                    "subject_key": key,
                    "period": period,
                    "metric_family": "CAPACITY",
                    "capacity_units": capacity,
                    "utilization_pct": utilization_pct,
                    "yield_pct": yield_pct,
                    "utilized_units": utilized_units,
                    "good_units": utilized_units * yield_pct // 100,
                },
            )
    for product_index, name in enumerate(PRODUCTS):
        for period_index, period in enumerate(PERIODS):
            seasonal_delta = ((period_index * 7 + product_index * 11) % 31) - 10
            demand_units = (
                52_000 + product_index * 8_500 + period_index * 1_750 + seasonal_delta * 320
            )
            add_node(
                "MetricObservation",
                f"product-{product_index + 1}-{period}",
                f"{name} demand observation {period}",
                classification=2 if product_index in {0, 1, 7} else 1,
                properties={
                    "subject_type": "Product",
                    "subject_key": f"product-{product_index + 1}",
                    "period": period,
                    "metric_family": "DEMAND",
                    "demand_units": demand_units,
                    "price_index": round(90 + product_index * 2.5 + period_index * 1.2, 2),
                },
            )
    for asset in catalog_assets:
        add_node(
            "Dataset",
            asset.key,
            asset.name,
            classification=asset.classification,
            properties={"platform": asset.platform, "description": asset.description},
        )

    edges: dict[UUID, GraphEdge] = {}

    def add_edge(
        edge_type: str,
        key: str,
        source: str,
        target: str,
        *,
        properties: dict[str, Any] | None = None,
    ) -> None:
        edge_id = stable_id(f"edge:{edge_type}:{key}")
        edges[edge_id] = GraphEdge(
            edge_id=edge_id,
            source_entity_id=references[source],
            target_entity_id=references[target],
            edge_type=edge_type,
            properties={
                "seed_namespace": SEED_NAMESPACE,
                "pack_version": PACK_VERSION,
                "is_synthetic": True,
                **(properties or {}),
            },
            classification=max(
                nodes[references[source]].classification,
                nodes[references[target]].classification,
            ),
            provenance=provenance,
        )

    for index in range(len(STAGES) - 1):
        add_edge(
            "FLOWS_TO",
            f"stage-{index + 1}",
            f"ValueChainStage:{STAGES[index][0]}",
            f"ValueChainStage:{STAGES[index + 1][0]}",
        )
    for stage_key, _ in STAGES:
        for company_index in range(2):
            add_edge(
                "PARTICIPATES_IN",
                f"{stage_key}-{company_index + 1}",
                f"Company:{stage_key}-{company_index + 1}",
                f"ValueChainStage:{stage_key}",
            )
    for index, (facility_key, *_rest) in enumerate(FACILITIES):
        stage_key = STAGES[index][0]
        add_edge(
            "OPERATES",
            facility_key,
            f"Company:{stage_key}-1",
            f"Facility:{facility_key}",
        )
    for index in range(len(MATERIALS)):
        add_edge(
            "SUPPLIES_TO",
            f"material-{index + 1}",
            f"Material:material-{index + 1}",
            "ValueChainStage:fabrication",
        )
    for index in range(len(EQUIPMENT)):
        add_edge(
            "ENABLES",
            f"equipment-{index + 1}",
            f"EquipmentFamily:equipment-{index + 1}",
            f"ProcessStep:process-{index + 3}",
        )
    for index in range(len(PROCESSES) - 1):
        add_edge(
            "PRECEDES",
            f"process-{index + 1}",
            f"ProcessStep:process-{index + 1}",
            f"ProcessStep:process-{index + 2}",
        )
    for facility_index, (facility_key, *_rest) in enumerate(FACILITIES):
        for offset in range(2):
            process_index = facility_index * 2 + offset + 1
            add_edge(
                "USES",
                f"{facility_key}-process-{process_index}",
                f"Facility:{facility_key}",
                f"ProcessStep:process-{process_index}",
            )
    for index in range(len(PRODUCTS)):
        add_edge(
            "PRODUCES",
            f"product-{index + 1}",
            f"ProcessStep:process-{index + 5}",
            f"Product:product-{index + 1}",
        )
    for risk_index in range(len(RISKS)):
        for offset in range(2):
            stage_key = STAGES[(risk_index * 2 + offset) % len(STAGES)][0]
            add_edge(
                "AFFECTS",
                f"risk-{risk_index + 1}-{stage_key}",
                f"RiskFactor:risk-{risk_index + 1}",
                f"ValueChainStage:{stage_key}",
            )
    for index, asset in enumerate(catalog_assets):
        stage_key = STAGES[index % len(STAGES)][0]
        add_edge(
            "DESCRIBES",
            asset.key,
            f"Dataset:{asset.key}",
            f"ValueChainStage:{stage_key}",
        )
    for index in range(6):
        add_edge(
            "DEPENDS_ON",
            f"product-{index + 1}-material-{index + 1}",
            f"Product:product-{index + 1}",
            f"Material:material-{index + 1}",
        )
    for facility_index, (key, *_rest) in enumerate(FACILITIES):
        for period in PERIODS:
            add_edge(
                "OBSERVES",
                f"facility-{facility_index + 1}-{period}",
                f"MetricObservation:facility-{key}-{period}",
                f"Facility:{key}",
            )
    for product_index in range(len(PRODUCTS)):
        for period in PERIODS:
            add_edge(
                "OBSERVES",
                f"product-{product_index + 1}-{period}",
                f"MetricObservation:product-{product_index + 1}-{period}",
                f"Product:product-{product_index + 1}",
            )

    snapshot = GraphSnapshot(nodes=nodes, edges=edges)
    if len(nodes) != 257 or len(edges) != 279:
        raise RuntimeError(
            f"Seed topology changed unexpectedly: {len(nodes)} nodes, {len(edges)} edges"
        )
    logical_hash = hashlib.sha256(
        f"{snapshot.content_hash()}:{_catalog_hash(catalog_assets)}".encode()
    ).hexdigest()
    return SemiconductorPack(
        snapshot=snapshot,
        catalog_assets=catalog_assets,
        logical_hash=logical_hash,
    )


def _load_catalog_assets() -> tuple[CatalogSeed, ...]:
    path = seed_root() / "semiconductor" / "data" / "catalog_assets.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(
            CatalogSeed(
                key=row["key"],
                name=row["name"],
                description=row["description"],
                platform=row["platform"],
                classification=int(row["classification"]),
            )
            for row in csv.DictReader(handle)
        )


def _catalog_hash(assets: tuple[CatalogSeed, ...]) -> str:
    document = [
        {
            "key": item.key,
            "name": item.name,
            "description": item.description,
            "platform": item.platform,
            "classification": item.classification,
        }
        for item in assets
    ]
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def seed_root() -> Path:
    configured = os.environ.get("DATARIVER_SEED_ROOT")
    candidates = (
        (Path(configured),)
        if configured
        else (Path.cwd() / "seed", Path(__file__).resolve().parents[4] / "seed")
    )
    for candidate in candidates:
        if (candidate / "semiconductor" / "data" / "catalog_assets.csv").is_file():
            return candidate
    attempted = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Semiconductor seed assets not found under: {attempted}")
