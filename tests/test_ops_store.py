from pathlib import Path

from app.services.ops_store import OpsStore


def test_ops_store_management_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUPPORT_DB_PATH", str(tmp_path / "ops.db"))
    store = OpsStore()
    store.initialize()

    assert len(store.list_workflows()) == 3
    assert len(store.list_documents()) == 3
    assert len(store.list_integrations()) == 4
    assert len(store.list_failed_jobs()) == 2

    workflow = store.update_workflow("wf_delivery", "PAUSED")
    assert workflow is not None
    assert workflow["status"] == "PAUSED"

    document = store.create_document(
        {
            "title": "사이즈 안내 정책",
            "category": "상품",
            "content": "상품 상세 옵션에 표시된 사이즈별 재고를 기준으로 고객에게 안내합니다.",
            "source": "테스트",
            "status": "PUBLISHED",
        }
    )
    assert document["status"] == "PUBLISHED"
    assert document["chunk_count"] == 1

    job = store.retry_failed_job("job_stock_context")
    assert job is not None
    assert job["status"] == "RESOLVED"
    assert job["retry_count"] == 2
    assert len(store.list_audit_logs()) == 4
