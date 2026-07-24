from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from datariver.application.errors import ExternalDependencyError
from datariver.application.knowledge_pipeline_ports import (
    KnowledgePipelineRuntime,
    KnowledgeSourceSpoolReader,
    StreamingPageAwarePdfParser,
)
from datariver.application.knowledge_source_job_contracts import KnowledgeSourceJobClaim
from datariver.application.knowledge_source_job_ports import KnowledgeSourceJobWorkerStore
from datariver.application.services.knowledge_pipeline import KnowledgeSourcePipeline
from datariver.domain.common import ConflictError, DomainError


class _JobBecameStale(Exception):
    pass


class KnowledgeSourceWorker:
    def __init__(
        self,
        *,
        store: KnowledgeSourceJobWorkerStore,
        source_reader: KnowledgeSourceSpoolReader,
        parser: StreamingPageAwarePdfParser,
        runtime_resolver: Callable[
            [KnowledgeSourceJobClaim],
            Awaitable[KnowledgePipelineRuntime],
        ],
        worker_fingerprint: str,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> None:
        self._store = store
        self._source_reader = source_reader
        self._parser = parser
        self._runtime_resolver = runtime_resolver
        self._worker_fingerprint = worker_fingerprint
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(self) -> bool:
        claim = await self._store.claim_next(
            worker_fingerprint=self._worker_fingerprint,
            lease_seconds=self._lease_seconds,
            maximum_attempts=self._maximum_attempts,
        )
        if claim is None:
            return False
        spooled = None
        try:
            runtime = await self._preflight(claim)
            if runtime is None:
                return True
            spooled = await self._source_reader.spool_snapshot(source=claim.source)
            await self._store.renew(
                claim=claim,
                lease_seconds=self._lease_seconds,
                stage="SOURCE_READ",
                progress={},
            )
            pages = await asyncio.to_thread(
                self._parser.parse_stream,
                spooled.stream,
            )
            runtime = await self._preflight(claim)
            if runtime is None:
                return True

            async def checkpoint(stage: str, progress: dict[str, int]) -> None:
                if await self._preflight(claim) is None:
                    raise _JobBecameStale
                await self._store.renew(
                    claim=claim,
                    lease_seconds=self._lease_seconds,
                    stage=stage,
                    progress=progress,
                )

            pipeline = KnowledgeSourcePipeline(
                reader=self._source_reader,
                parser=self._parser,
                embedding=runtime.embedding,
                extractor=runtime.extractor,
            )
            analysis = await pipeline.analyze_pages(
                source=claim.source,
                pages=pages,
                entity_types=claim.entity_types,
                edge_types=claim.edge_types,
                embedding_binding=claim.pins.embedding_binding,
                extraction_binding=claim.pins.extraction_binding,
                checkpoint=checkpoint,
            )
            await self._store.renew(
                claim=claim,
                lease_seconds=self._lease_seconds,
                stage="FINALIZING",
                progress={
                    "completed_pages": len(analysis.pages),
                    "total_pages": len(analysis.pages),
                },
            )
            current_runtime = await self._runtime_resolver(claim)
            await self._store.finalize(
                claim=claim,
                analysis=analysis,
                current_embedding_binding=current_runtime.bindings.embedding,
                current_extraction_binding=current_runtime.bindings.extraction,
            )
        except _JobBecameStale:
            pass
        except ConflictError as error:
            if error.details.get("code") == "CANCEL_REQUESTED":
                await self._store.mark_cancelled(claim=claim)
            elif error.details.get("code") != "LEASE_SUPERSEDED":
                await self._store.mark_failed(
                    claim=claim,
                    failure_code=_domain_failure_code(error),
                    retryable=False,
                )
        except DomainError as error:
            await self._store.mark_failed(
                claim=claim,
                failure_code=_domain_failure_code(error),
                retryable=(
                    isinstance(error, ExternalDependencyError)
                    and bool(error.details.get("retryable", False))
                ),
            )
        except Exception as error:
            await self._store.mark_failed(
                claim=claim,
                failure_code=f"UNEXPECTED_{type(error).__name__}"[:100].upper(),
                retryable=True,
            )
        finally:
            if spooled is not None:
                spooled.close()
        return True

    async def _preflight(
        self,
        claim: KnowledgeSourceJobClaim,
    ) -> KnowledgePipelineRuntime | None:
        runtime = await self._runtime_resolver(claim)
        if (
            runtime.bindings.embedding.to_document() != claim.pins.embedding_binding.to_document()
            or runtime.bindings.extraction.to_document()
            != claim.pins.extraction_binding.to_document()
        ):
            await self._store.mark_stale(
                claim=claim,
                failure_code="STALE_MODEL_BINDING",
            )
            return None
        drift_code = await self._store.ensure_current(
            claim=claim,
            current_embedding_binding=runtime.bindings.embedding,
            current_extraction_binding=runtime.bindings.extraction,
        )
        if drift_code is not None:
            await self._store.mark_stale(
                claim=claim,
                failure_code=drift_code,
            )
            return None
        return runtime


def _domain_failure_code(error: DomainError) -> str:
    value = str(error.details.get("provider_code") or error.details.get("code") or error.code)
    normalized = "".join(
        character if character.isascii() and character.isalnum() else "_" for character in value
    ).strip("_")
    return (normalized or type(error).__name__).upper()[:100]
