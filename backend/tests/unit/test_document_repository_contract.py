from backend.app.retrieval.rrf import RankedCandidate
from backend.app.storage.document_repository import canonical_evidence_pipeline
from backend.app.storage.schema import required_mongo_indexes


def test_document_fact_plane_defines_required_unique_and_lookup_indexes() -> None:
    indexes = required_mongo_indexes()

    version_indexes = {item.name: item for item in indexes["document_versions"]}
    chunk_indexes = {item.name: item for item in indexes["chunks"]}

    assert version_indexes["uq_versions_document_version"].unique is True
    assert version_indexes["uq_versions_sha256"].unique is True
    assert chunk_indexes["uq_chunks_version_ordinal"].unique is True
    assert "ix_versions_fact_eligible" in version_indexes


def test_canonical_evidence_pipeline_requires_active_version_and_current_document_pointer() -> None:
    pipeline = canonical_evidence_pipeline(
        [RankedCandidate("chunk-1", "doc-1", "ver-1", 1)],
        active_current_only=True,
    )

    final_match = next(
        stage["$match"]
        for stage in pipeline
        if "$match" in stage and "$expr" in stage["$match"]
    )

    assert final_match["version.status"]["$in"] == ["ACTIVE", "ACTIVE_WITH_WARNING"]
    assert final_match["$expr"] == {"$eq": ["$document.current_active_version_id", "$version._id"]}
