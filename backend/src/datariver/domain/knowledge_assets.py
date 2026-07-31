from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from datariver.domain.common import ValidationError, canonical_json_hash

MAX_ROUTE_TERMS = 50
MAX_ROUTE_TERM_LENGTH = 80


def _normalize_route_term(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip().casefold()
    if (
        not normalized
        or len(normalized) > MAX_ROUTE_TERM_LENGTH
        or any(character in normalized for character in "\r\n\x00")
    ):
        raise ValidationError(
            f"A Knowledge route term must contain 1 through {MAX_ROUTE_TERM_LENGTH} "
            "trimmed characters on one line."
        )
    return normalized


def normalize_route_terms(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > MAX_ROUTE_TERMS:
        raise ValidationError(
            f"A Knowledge delivery policy accepts at most {MAX_ROUTE_TERMS} terms per condition."
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _normalize_route_term(value)
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class KnowledgeDeliveryPolicy:
    policy_id: UUID
    workspace_id: UUID
    graph_id: UUID
    api_enabled: bool
    chat_enabled: bool
    priority: int
    match_any_terms: tuple[str, ...]
    match_all_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime
    version: int

    def content_hash(self) -> str:
        return canonical_json_hash(
            {
                "contract": "KNOWLEDGE_DELIVERY_POLICY_V1",
                "policy_id": str(self.policy_id),
                "workspace_id": str(self.workspace_id),
                "graph_id": str(self.graph_id),
                "api_enabled": self.api_enabled,
                "chat_enabled": self.chat_enabled,
                "priority": self.priority,
                "match_any_terms": list(self.match_any_terms),
                "match_all_terms": list(self.match_all_terms),
                "excluded_terms": list(self.excluded_terms),
                "version": self.version,
            }
        )

    def matches(self, question: str) -> bool:
        if not self.chat_enabled:
            return False
        normalized_question = unicodedata.normalize("NFC", question).casefold()
        if any(term in normalized_question for term in self.excluded_terms):
            return False
        if self.match_all_terms and not all(
            term in normalized_question for term in self.match_all_terms
        ):
            return False
        return not self.match_any_terms or any(
            term in normalized_question for term in self.match_any_terms
        )


def validate_delivery_policy(
    *,
    chat_enabled: bool,
    priority: int,
    match_any_terms: tuple[str, ...],
    match_all_terms: tuple[str, ...],
    excluded_terms: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not 0 <= priority <= 1_000:
        raise ValidationError("Knowledge Chat routing priority must be between 0 and 1,000.")
    any_terms = normalize_route_terms(match_any_terms)
    all_terms = normalize_route_terms(match_all_terms)
    excluded = normalize_route_terms(excluded_terms)
    positive = set(any_terms) | set(all_terms)
    if chat_enabled and not positive:
        raise ValidationError(
            "An enabled Knowledge Chat route requires at least one ANY or ALL term."
        )
    if positive.intersection(excluded):
        raise ValidationError("A Knowledge Chat route term cannot be both required and excluded.")
    if set(any_terms).intersection(all_terms):
        raise ValidationError(
            "A Knowledge Chat route term cannot appear in both ANY and ALL conditions."
        )
    return any_terms, all_terms, excluded
