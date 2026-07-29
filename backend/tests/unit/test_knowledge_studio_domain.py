from __future__ import annotations

from dataclasses import replace

import pytest

from datariver.domain.common import ConflictError, PreconditionFailedError, ValidationError
from datariver.domain.knowledge_studio import (
    ABoxMappingMethod,
    ABoxMappingRuleInput,
    StudioDraftState,
    TBoxBlockPrecedence,
    TBoxElementInput,
    TBoxElementKind,
    TBoxOperationInput,
    TBoxOperationKind,
    require_studio_transition,
    require_studio_version,
    validate_abox_mapping_rules,
    validate_endpoint_alias,
    validate_studio_name,
    validate_tbox_element_set,
)
from datariver.interfaces.http.routes.knowledge_studio import _expected_version


@pytest.mark.parametrize(
    "value",
    [
        "semiconductor_materials",
        "a12",
        "metadata_lineage_2026",
    ],
)
def test_endpoint_alias_accepts_the_approved_ascii_contract(value: str) -> None:
    assert validate_endpoint_alias(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "ab",
        "1graph",
        "Graph",
        "graph-name",
        "graph name",
        "그래프",
        "a" * 101,
    ],
)
def test_endpoint_alias_rejects_values_outside_the_approved_contract(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_endpoint_alias(value)


def test_tbox_precedence_enforces_weight_and_ordinal_bounds() -> None:
    assert sorted(
        [
            TBoxBlockPrecedence(weight=50, ordinal=2),
            TBoxBlockPrecedence(weight=90, ordinal=0),
            TBoxBlockPrecedence(weight=50, ordinal=3),
        ],
        key=lambda value: (value.weight, value.ordinal),
    )[-1] == TBoxBlockPrecedence(weight=90, ordinal=0)

    with pytest.raises(ValidationError):
        TBoxBlockPrecedence(weight=101, ordinal=0)
    with pytest.raises(ValidationError):
        TBoxBlockPrecedence(weight=50, ordinal=-1)


def test_tbox_typed_operations_enforce_shape_and_text_only_vector_targets() -> None:
    entity = TBoxElementInput(
        stable_element_id="class:Document",
        kind=TBoxElementKind.CLASS,
        canonical_name="Document",
        display_name="Document",
    )
    description = TBoxElementInput(
        stable_element_id="property:Document:description",
        kind=TBoxElementKind.PROPERTY,
        canonical_name="description",
        display_name="Description",
        parent_stable_element_id=entity.stable_element_id,
        data_type="TEXT",
        nullable=True,
        vector_index_enabled=True,
    )
    validate_tbox_element_set((entity, description))
    TBoxOperationInput(
        operation=TBoxOperationKind.UPSERT_ELEMENT,
        stable_element_id=description.stable_element_id,
        element=description,
    ).validate()

    with pytest.raises(ValidationError, match="STRING or TEXT"):
        TBoxElementInput(
            stable_element_id="property:Document:amount",
            kind=TBoxElementKind.PROPERTY,
            canonical_name="amount",
            display_name="Amount",
            parent_stable_element_id=entity.stable_element_id,
            data_type="INTEGER",
            nullable=False,
            vector_index_enabled=True,
        ).validate()

    with pytest.raises(ValidationError, match="accepted Class"):
        validate_tbox_element_set((description,))


def test_tbox_class_hierarchy_requires_classes_and_rejects_cycles() -> None:
    root = TBoxElementInput(
        stable_element_id="class:Asset",
        kind=TBoxElementKind.CLASS,
        canonical_name="Asset",
        display_name="Asset",
    )
    dataset = TBoxElementInput(
        stable_element_id="class:Dataset",
        kind=TBoxElementKind.CLASS,
        canonical_name="Dataset",
        display_name="Dataset",
        parent_stable_element_id=root.stable_element_id,
    )
    validate_tbox_element_set((root, dataset))

    with pytest.raises(ValidationError, match="accepted Class"):
        validate_tbox_element_set(
            (
                replace(dataset, parent_stable_element_id="class:Missing"),
                root,
            )
        )

    with pytest.raises(ValidationError, match="cycle"):
        validate_tbox_element_set(
            (
                replace(root, parent_stable_element_id=dataset.stable_element_id),
                dataset,
            )
        )


def test_tbox_external_metadata_reference_is_opaque_but_bounded() -> None:
    referenced = TBoxElementInput(
        stable_element_id="class:Dataset",
        kind=TBoxElementKind.CLASS,
        canonical_name="Dataset",
        display_name="Dataset",
        metadata_reference_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,orders,PROD)",
    )
    referenced.validate()

    with pytest.raises(ValidationError, match="metadata reference URN"):
        replace(referenced, metadata_reference_urn=" unsafe ").validate()


def test_studio_lifecycle_requires_review_before_publication() -> None:
    require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.REVIEW)
    require_studio_transition(StudioDraftState.REVIEW, StudioDraftState.PUBLISHED)
    require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.DISCARDED)

    with pytest.raises(ConflictError):
        require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.PUBLISHED)
    with pytest.raises(ConflictError):
        require_studio_transition(StudioDraftState.DISCARDED, StudioDraftState.DRAFT)


def test_studio_basic_information_and_version_fence_are_strict() -> None:
    assert validate_studio_name("반도체 소재 그래프") == "반도체 소재 그래프"
    require_studio_version(4, 4)

    with pytest.raises(ValidationError):
        validate_studio_name(" surrounding ")
    with pytest.raises(PreconditionFailedError):
        require_studio_version(5, 4)


@pytest.mark.parametrize("value", ["1", '"0"', '"01"', '"x"', '"1" "'])
def test_studio_if_match_requires_one_canonical_quoted_positive_version(value: str) -> None:
    with pytest.raises(ValidationError):
        _expected_version(value)

    assert _expected_version('"12"') == 12


def test_abox_class_mapping_accepts_only_selected_class_and_owned_properties() -> None:
    validate_abox_mapping_rules(
        target_kind=TBoxElementKind.CLASS,
        target_stable_element_id="class.employee",
        property_parent_by_id={"property.employee.name": "class.employee"},
        allowed_source_field_paths=frozenset({"emp_id", "emp_nm"}),
        rules=(
            ABoxMappingRuleInput(
                method=ABoxMappingMethod.SUBJECT_ID,
                source_field_path="emp_id",
                target_stable_element_id="class.employee",
            ),
            ABoxMappingRuleInput(
                method=ABoxMappingMethod.PROPERTY,
                source_field_path="emp_nm",
                target_stable_element_id="property.employee.name",
            ),
        ),
    )

    with pytest.raises(ValidationError, match="owned by the selected Class"):
        validate_abox_mapping_rules(
            target_kind=TBoxElementKind.CLASS,
            target_stable_element_id="class.employee",
            property_parent_by_id={"property.department.name": "class.department"},
            allowed_source_field_paths=frozenset({"dept_nm"}),
            rules=(
                ABoxMappingRuleInput(
                    method=ABoxMappingMethod.PROPERTY,
                    source_field_path="dept_nm",
                    target_stable_element_id="property.department.name",
                ),
            ),
        )


def test_abox_mapping_rejects_unreturned_fields_and_duplicate_subject_ids() -> None:
    with pytest.raises(ValidationError, match="server-returned Dataset schema"):
        validate_abox_mapping_rules(
            target_kind=TBoxElementKind.CLASS,
            target_stable_element_id="class.employee",
            property_parent_by_id={},
            allowed_source_field_paths=frozenset({"emp_id"}),
            rules=(
                ABoxMappingRuleInput(
                    method=ABoxMappingMethod.SUBJECT_ID,
                    source_field_path="invented_column",
                    target_stable_element_id="class.employee",
                ),
            ),
        )

    with pytest.raises(ValidationError, match="at most one SUBJECT_ID"):
        validate_abox_mapping_rules(
            target_kind=TBoxElementKind.CLASS,
            target_stable_element_id="class.employee",
            property_parent_by_id={},
            allowed_source_field_paths=frozenset({"emp_id", "legacy_emp_id"}),
            rules=(
                ABoxMappingRuleInput(
                    method=ABoxMappingMethod.SUBJECT_ID,
                    source_field_path="emp_id",
                    target_stable_element_id="class.employee",
                ),
                ABoxMappingRuleInput(
                    method=ABoxMappingMethod.SUBJECT_ID,
                    source_field_path="legacy_emp_id",
                    target_stable_element_id="class.employee",
                ),
            ),
        )
