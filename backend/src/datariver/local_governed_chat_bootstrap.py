from __future__ import annotations

import argparse
import asyncio
import json

from datariver.application.services.local_governed_chat_bootstrap import (
    LocalGovernedChatBootstrapConfig,
    LocalGovernedChatBootstrapService,
)
from datariver.bootstrap import LOCAL_DEMO_IDENTITIES, LOCAL_SUBJECT_ID, LOCAL_WORKSPACE_ID
from datariver.config import get_settings
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.domain.retention import RetentionRules
from datariver.infrastructure.db.local_governed_chat_bootstrap import (
    SqlLocalGovernedChatBootstrapUnitOfWork,
)
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.llm.runtime_binding import (
    resolve_interactive_runtime_bindings,
)
from datariver.infrastructure.secrets import SecretResolver

LOCAL_GOVERNANCE_CHECKER_ID = next(
    identity.subject_id for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize the local development governed Chat contracts."
    )
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--attestation-evidence-reference", required=True)
    parser.add_argument("--attestation-valid-days", type=int, required=True)
    parser.add_argument("--restricted-search-grant-maximum-days", type=int, required=True)
    parser.add_argument(
        "--maximum-classification",
        choices=("PUBLIC", "INTERNAL", "CONFIDENTIAL"),
        default="INTERNAL",
    )
    parser.add_argument("--completed-operation-days", type=int, required=True)
    parser.add_argument("--chat-content-days", type=int, required=True)
    parser.add_argument("--audit-online-months", type=int, required=True)
    parser.add_argument("--immutable-archive-years", type=int, required=True)
    return parser


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("Local governed Chat bootstrap is development-only.")
    database = Database(
        settings.database_url,
        password=SecretResolver().resolve(settings.database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-governed-chat-bootstrap",
    )
    try:
        result = await LocalGovernedChatBootstrapService(
            lambda: SqlLocalGovernedChatBootstrapUnitOfWork(database.session_factory)
        ).bootstrap(
            workspace_id=LOCAL_WORKSPACE_ID,
            maker_id=LOCAL_SUBJECT_ID,
            checker_id=LOCAL_GOVERNANCE_CHECKER_ID,
            bindings=resolve_interactive_runtime_bindings(settings),
            config=LocalGovernedChatBootstrapConfig(
                jurisdiction=arguments.jurisdiction,
                region=arguments.region,
                attestation_evidence_reference=arguments.attestation_evidence_reference,
                attestation_valid_days=arguments.attestation_valid_days,
                restricted_search_grant_maximum_days=(
                    arguments.restricted_search_grant_maximum_days
                ),
                maximum_classification=Classification[arguments.maximum_classification],
                retention_rules=RetentionRules(
                    completed_operation_days=arguments.completed_operation_days,
                    chat_content_days=arguments.chat_content_days,
                    audit_online_months=arguments.audit_online_months,
                    immutable_archive_years=arguments.immutable_archive_years,
                ),
            ),
            now=utc_now(),
        )
        return {
            "classification_policy_id": str(result.classification_policy_id),
            "composition_profile_version_id": str(result.composition_profile_version_id),
            "embedding_profile_version_id": str(result.embedding_profile_version_id),
            "reranker_profile_version_id": str(result.reranker_profile_version_id),
            "retention_policy_id": str(result.retention_policy_id),
            "reused_profile_count": result.reused_profile_count,
            "reused_classification_policy": result.reused_classification_policy,
            "reused_retention_policy": result.reused_retention_policy,
        }
    finally:
        await database.close()


def main() -> None:
    arguments = _parser().parse_args()
    print(json.dumps(asyncio.run(_run(arguments)), sort_keys=True))


if __name__ == "__main__":
    main()
