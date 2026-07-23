from __future__ import annotations

from datariver.domain.authz import SubjectAttributes
from datariver.domain.common import ForbiddenError

REGISTRATION_WORKER_GROUP = "registration-workers"
SERVICE_ACCOUNT_GROUP = "service-accounts"
SERVICE_ACCOUNT_JOB_FUNCTION = "SERVICE_ACCOUNT"
DATA_STEWARD_JOB_FUNCTION = "DATA_STEWARD"
DATA_STEWARD_GROUP = "data-stewards"
SECURITY_ADMIN_GROUP = "security-administrators"


def require_registration_worker_identity(
    subject: SubjectAttributes,
) -> SubjectAttributes:
    if (
        not subject.active
        or subject.job_function != SERVICE_ACCOUNT_JOB_FUNCTION
        or SERVICE_ACCOUNT_GROUP not in subject.groups
        or REGISTRATION_WORKER_GROUP not in subject.groups
    ):
        raise ForbiddenError(
            "The registration execution boundary requires an active purpose-bound service identity."
        )
    return subject


def require_registration_operator_identity(
    subject: SubjectAttributes,
) -> SubjectAttributes:
    """Limit browser Manual/Bulk operation to canonical human Admin/Data Steward identities."""

    is_service = (
        subject.job_function == SERVICE_ACCOUNT_JOB_FUNCTION
        or SERVICE_ACCOUNT_GROUP in subject.groups
    )
    is_admin = SECURITY_ADMIN_GROUP in subject.groups
    is_steward = (
        subject.job_function == DATA_STEWARD_JOB_FUNCTION and DATA_STEWARD_GROUP in subject.groups
    )
    if not subject.active or is_service or not (is_admin or is_steward):
        raise ForbiddenError("An active human Admin or Data Steward is required.")
    return subject
