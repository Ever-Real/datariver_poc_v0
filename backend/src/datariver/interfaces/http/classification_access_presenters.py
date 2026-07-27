from __future__ import annotations

from datariver.domain.classification_access import (
    ClassificationAccessPolicy,
    RestrictedSearchGrant,
)
from datariver.domain.inference_provider import InferenceProviderProfileVersion
from datariver.interfaces.http.classification_access_schemas import (
    ClassificationPolicyResponse,
    ClassificationRuleResponse,
    InferenceProviderProfileResponse,
    ProviderAttestationResponse,
    RestrictedSearchGrantResponse,
)


def classification_policy_response(
    policy: ClassificationAccessPolicy,
) -> ClassificationPolicyResponse:
    return ClassificationPolicyResponse(
        policy_id=policy.policy_id,
        policy_number=policy.policy_number,
        required_jurisdiction=policy.required_jurisdiction,
        restricted_search_grant_maximum_days=(policy.restricted_search_grant_maximum_days),
        rules=[
            ClassificationRuleResponse(
                classification=rule.classification.name,
                search_mode=rule.search_mode,
                chat_mode=rule.chat_mode,
                provider_profile_version_id=rule.provider_profile_version_id,
                embedding_provider_profile_version_id=(rule.embedding_provider_profile_version_id),
                reranker_provider_profile_version_id=(rule.reranker_provider_profile_version_id),
            )
            for rule in policy.rules
        ],
        payload_hash=policy.payload_hash,
        requester_id=policy.requester_id,
        request_reason=policy.request_reason,
        request_policy_decision_id=policy.request_policy_decision_id,
        state=policy.state,
        checker_id=policy.checker_id,
        decision_reason=policy.decision_reason,
        decision_policy_decision_id=policy.decision_policy_decision_id,
        decided_at=policy.decided_at,
        superseded_by=policy.superseded_by,
        supersede_reason=policy.supersede_reason,
        supersede_policy_decision_id=policy.supersede_policy_decision_id,
        superseded_at=policy.superseded_at,
        version=policy.version,
    )


def restricted_search_grant_response(
    grant: RestrictedSearchGrant,
) -> RestrictedSearchGrantResponse:
    return RestrictedSearchGrantResponse(
        grant_id=grant.grant_id,
        classification_policy_id=grant.classification_policy_id,
        classification_policy_hash=grant.classification_policy_hash,
        subject_id=grant.subject_id,
        scope=grant.scope,
        scope_id=grant.scope_id,
        purpose=grant.purpose,
        valid_from=grant.valid_from,
        expires_at=grant.expires_at,
        payload_hash=grant.payload_hash,
        requester_id=grant.requester_id,
        request_reason=grant.request_reason,
        request_policy_decision_id=grant.request_policy_decision_id,
        state=grant.state,
        checker_id=grant.checker_id,
        decision_reason=grant.decision_reason,
        decision_policy_decision_id=grant.decision_policy_decision_id,
        decided_at=grant.decided_at,
        revoked_by=grant.revoked_by,
        revocation_reason=grant.revocation_reason,
        revocation_policy_decision_id=grant.revocation_policy_decision_id,
        revoked_at=grant.revoked_at,
        version=grant.version,
    )


def inference_provider_profile_response(
    value: InferenceProviderProfileVersion,
) -> InferenceProviderProfileResponse:
    profile = value.profile
    return InferenceProviderProfileResponse(
        provider_profile_version_id=value.provider_profile_version_id,
        profile_key=profile.profile_key,
        profile_version=value.profile_version,
        server_route_key=profile.server_route_key,
        kind=profile.kind,
        provider_identity=profile.provider_identity,
        model_identity=profile.model_identity,
        deployment_identity=profile.deployment_identity,
        jurisdiction=profile.jurisdiction,
        region=profile.region,
        maximum_classification=profile.maximum_classification.name,
        residency_attestation=ProviderAttestationResponse(
            fingerprint=profile.residency_attestation.fingerprint,
            observed_at=profile.residency_attestation.observed_at,
            expires_at=profile.residency_attestation.expires_at,
        ),
        zero_retention_attestation=ProviderAttestationResponse(
            fingerprint=profile.zero_retention_attestation.fingerprint,
            observed_at=profile.zero_retention_attestation.observed_at,
            expires_at=profile.zero_retention_attestation.expires_at,
        ),
        payload_hash=value.payload_hash,
        maker_id=value.maker_id,
        proposal_reason=value.proposal_reason,
        proposal_policy_decision_id=value.proposal_policy_decision_id,
        proposed_at=value.proposed_at,
        state=value.state,
        checker_id=value.checker_id,
        decision_reason=value.decision_reason,
        decision_policy_decision_id=value.decision_policy_decision_id,
        decided_at=value.decided_at,
        revoked_by=value.revoked_by,
        revocation_reason=value.revocation_reason,
        revocation_policy_decision_id=value.revocation_policy_decision_id,
        revoked_at=value.revoked_at,
        version=value.version,
    )
