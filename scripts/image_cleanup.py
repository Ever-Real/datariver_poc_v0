"""Conservative inventory and opt-in cleanup of owned source images only.

No build cache or untagged images are selected. Docker's non-force conflict
checks remain the final guard against containers or tags changing after a scan.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime


class ImageCleanupError(RuntimeError):
    """An inventory cannot establish the prerequisites for safe cleanup."""


_TAG = re.compile(r"datariver-dev-deploy-source:([0-9a-f]{12})(?:-[0-9]{8}T[0-9]{12}Z)?")
_ID = re.compile(r"sha256:[0-9a-f]{64}")
_SHA = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}")
_IMAGE_FORMAT = ('{"Id":{{json .Id}},"RepoTags":{{json .RepoTags}},'
                 '"Created":{{json .Created}},"Labels":{{json .Config.Labels}}}')


def _docker(*args: str) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageCleanupError("DOCKER_OPERATION_FAILED") from exc
    if result.returncode:
        # Do not expose Docker output, which can contain host paths or metadata.
        raise ImageCleanupError("DOCKER_OPERATION_FAILED")
    return result.stdout


def _image(ref: str) -> dict:
    try:
        value = json.loads(_docker("image", "inspect", "--format", _IMAGE_FORMAT, ref))
        if not isinstance(value, dict) or not _ID.fullmatch(value.get("Id", "")):
            raise ValueError
        tags = value.get("RepoTags")
        if tags is not None and (not isinstance(tags, list)
                                 or not all(isinstance(tag, str) for tag in tags)):
            raise ValueError
        return value
    except (ValueError, TypeError) as exc:
        raise ImageCleanupError("INVALID_IMAGE_INVENTORY") from exc


def _created(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    # Python 3.10 accepts only three or six fractional digits, whereas Docker
    # emits RFC3339 timestamps with up to nine. Normalize to datetime's
    # microsecond precision, matching the parsing behavior of newer Python.
    value = re.sub(
        r"(\d{2}:\d{2}:\d{2})\.(\d{1,9})(Z|[+-]\d{2}:\d{2})$",
        lambda match: f"{match[1]}.{match[2][:6].ljust(6, '0')}{match[3]}",
        value,
    )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _snapshot(protected: set[str], keep: int) -> tuple[list[dict], dict, set[str]]:
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 3:
        raise ImageCleanupError("KEEP_MUST_BE_AT_LEAST_THREE")
    if not isinstance(protected, set) or any(
        not isinstance(ref, str) or not _REF.fullmatch(ref) for ref in protected
    ):
        raise ImageCleanupError("INVALID_PROTECTED_REFERENCE")

    # Resolve every caller reference, including foreign images and references
    # outside the source inventory. Missing receipts must never be ignored.
    protected_ids = {_image(ref)["Id"] for ref in sorted(protected)}
    image_ids = set(_docker(
        "image", "ls", "--no-trunc", "--quiet", "--filter",
        "reference=datariver-dev-deploy-source:*",
    ).split())
    if any(not _ID.fullmatch(image_id) for image_id in image_ids):
        raise ImageCleanupError("INVALID_IMAGE_LIST")
    images = [_image(image_id) for image_id in sorted(image_ids)]
    if {item["Id"] for item in images} != image_ids:
        raise ImageCleanupError("IMAGE_ID_CHANGED")

    # Inspect only Image: avoid reading container environment/configuration.
    container_ids = set(_docker("container", "ls", "--all", "--quiet", "--no-trunc").split())
    if any(not _SHA.fullmatch(container_id) for container_id in container_ids):
        raise ImageCleanupError("INVALID_CONTAINER_LIST")
    container_images = set()
    for container_id in sorted(container_ids):
        try:
            image_id = json.loads(_docker(
                "container", "inspect", "--format", "{{json .Image}}", container_id,
            ))
            if not isinstance(image_id, str) or not _ID.fullmatch(image_id):
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ImageCleanupError("INVALID_CONTAINER_INVENTORY") from exc
        container_images.add(image_id)

    plan, fingerprints, eligible = [], {}, []
    for item in images:
        image_id = item["Id"]
        tags = sorted(set(item.get("RepoTags") or []))
        created = item.get("Created")
        labels = item.get("Labels")
        labels = labels if isinstance(labels, dict) else {}
        source = labels.get("io.datariver.source.sha256")
        revision = labels.get("org.opencontainers.image.revision")
        owned = [tag for tag in tags if _TAG.fullmatch(tag)]
        valid_labels = (
            isinstance(source, str) and bool(_SHA.fullmatch(source))
            and source == revision
            and all(_TAG.fullmatch(tag).group(1) == source[:12] for tag in owned)
        )
        timestamp = _created(created)
        if owned and valid_labels and timestamp is not None:
            eligible.append((timestamp, image_id))
        if not tags:
            reason = "UNTAGGED"
        elif len(owned) != len(tags):
            reason = "FOREIGN_TAG"
        elif not valid_labels:
            reason = "INVALID_SOURCE_LABELS"
        elif timestamp is None:
            reason = "INVALID_CREATED"
        elif image_id in container_images:
            reason = "CONTAINER_REFERENCE"
        elif image_id in protected_ids:
            reason = "PROTECTED_REFERENCE"
        else:
            reason = "ELIGIBLE_OLD_SOURCE_IMAGE"
        plan.append({
            "id": image_id, "tags": tags,
            "created": created if isinstance(created, str) else None,
            "disposition": "DELETE_CANDIDATE" if reason == "ELIGIBLE_OLD_SOURCE_IMAGE" else "KEEP",
            "reason": reason,
        })
        # Include source labels even when a changed label shares a tag prefix.
        fingerprints[image_id] = (tags, created, source, revision)

    newest = {image_id for _, image_id in sorted(eligible, reverse=True)[:keep]}
    for record in plan:
        if record["id"] in newest and record["disposition"] == "DELETE_CANDIDATE":
            record.update(disposition="KEEP", reason="LATEST_SOURCE_IMAGES")
    return plan, fingerprints, protected_ids


def inventory(protected: set[str], keep: int = 3) -> list[dict]:
    """Return sanitized KEEP/DELETE_CANDIDATE records; never mutate Docker."""
    return _snapshot(protected, keep)[0]


def cleanup(protected: set[str], keep: int = 3, apply: bool = False) -> dict:
    """Plan by default; apply removes unchanged candidates sequentially by ID.

    Returns plan/deleted/held record lists, an apply flag, and a counts mapping.
    Failed or changed candidates are held; there is no retry using force.
    """
    if not isinstance(apply, bool):
        raise ImageCleanupError("APPLY_MUST_BE_BOOLEAN")
    plan, fingerprints, protected_ids = _snapshot(protected, keep)
    deleted, held = [], []
    candidates = [record for record in plan if record["disposition"] == "DELETE_CANDIDATE"]
    if apply:
        # Retain original protected IDs even if a caller's tag moves later.
        protected = protected | protected_ids
        for index, record in enumerate(candidates):
            try:
                current, signatures, _ = _snapshot(protected, keep)
            except ImageCleanupError:
                held.extend({**item, "reason": "RECHECK_FAILED"} for item in candidates[index:])
                break
            current_record = next((item for item in current if item["id"] == record["id"]), None)
            if current_record != record or signatures.get(record["id"]) != fingerprints[record["id"]]:
                held.append({**record, "reason": "CANDIDATE_CHANGED"})
                continue
            try:
                _docker("image", "rm", record["id"])
            except ImageCleanupError:
                held.append({**record, "reason": "DELETE_REFUSED_OR_FAILED"})
            else:
                deleted.append(record.copy())
    return {
        "apply": apply, "plan": plan, "deleted": deleted, "held": held,
        "counts": {
            "plan": len(plan), "keep": len(plan) - len(candidates),
            "candidates": len(candidates), "deleted": len(deleted), "held": len(held),
        },
    }
