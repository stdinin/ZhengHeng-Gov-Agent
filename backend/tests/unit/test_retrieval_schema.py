from backend.app.retrieval.bm25 import policy_chunk_index_body
from backend.app.retrieval.dense import dense_collection_spec, versioned_collection_name


def test_opensearch_policy_chunk_mapping_keeps_filter_and_text_fields() -> None:
    mappings = policy_chunk_index_body()["mappings"]["properties"]

    assert mappings["chunk_id"]["type"] == "keyword"
    assert mappings["bm25_text"] == {"type": "text", "analyzer": "whitespace"}
    assert mappings["department_id"]["type"] == "keyword"
    assert mappings["version_id"]["type"] == "keyword"
    assert mappings["version_status"]["type"] == "keyword"
    assert mappings["active"]["type"] == "boolean"


def test_milvus_collection_spec_declares_primary_metadata_and_vector_dimensions() -> None:
    spec = dense_collection_spec(embedding_dim=1024, embedding_model="BAAI/bge-m3")

    assert spec.collection_name == "policy_chunks_dense__baai_bge_m3__d1024"
    assert spec.primary_key == "chunk_id"
    assert spec.embedding_dim == 1024
    assert spec.embedding_model == "BAAI/bge-m3"
    assert spec.metadata == {
        "zhengheng.embedding_model": "BAAI/bge-m3",
        "zhengheng.embedding_dimension": "1024",
    }
    assert set(spec.scalar_fields) >= {
        "document_id",
        "version_id",
        "department_id",
        "version_status",
        "active",
    }


def test_milvus_collection_spec_can_isolate_an_integration_collection_name() -> None:
    spec = dense_collection_spec(
        embedding_dim=4,
        embedding_model="test-model",
        collection_name="policy_chunks_dense_test",
    )

    assert spec.collection_name == "policy_chunks_dense_test"


def test_embedding_model_or_dimension_change_selects_a_new_collection_version() -> None:
    current = versioned_collection_name("policy_chunks_dense", "BAAI/bge-m3", 1024)
    new_model = versioned_collection_name("policy_chunks_dense", "BAAI/bge-large-zh-v1.5", 1024)
    new_dimension = versioned_collection_name("policy_chunks_dense", "BAAI/bge-m3", 768)

    assert current == "policy_chunks_dense__baai_bge_m3__d1024"
    assert new_model != current
    assert new_dimension != current
