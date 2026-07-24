import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.db_compat import Connection, PostgresConnection, database_url, is_postgres


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class OpsStore:
    def __init__(self) -> None:
        configured = os.getenv("SUPPORT_DB_PATH", "data/support.db")
        self.path = Path(configured)
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> Connection:
        if is_postgres():
            url = database_url()
            assert url is not None
            return PostgresConnection(url)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        connection = self.connect()
        try:
            if not is_postgres():
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    steps TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS integrations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_summary TEXT NOT NULL,
                    last_checked_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failed_jobs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    inquiry_id TEXT,
                    error_code TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._seed(connection)

    def _seed(self, connection: Connection) -> None:
        now = utc_now()
        workflows = [
            (
                "wf_delivery",
                "배송 문의 자동 응대",
                "배송 상태와 예정일을 조회해 고객에게 안내합니다.",
                "문의 분류: 배송",
                "ACTIVE",
                3,
                json.dumps(
                    ["문의 분류", "주문 조회", "정책 검증", "OpenRouter 답변"],
                    ensure_ascii=False,
                ),
                128,
                2,
                now,
            ),
            (
                "wf_returns",
                "반품 가능 여부 확인",
                "수령일과 상품 상태를 기준으로 반품 정책을 안내합니다.",
                "문의 분류: 반품·환불",
                "ACTIVE",
                2,
                json.dumps(["주문 확인", "반품 기한 계산", "상담원 이관 판단"], ensure_ascii=False),
                74,
                4,
                now,
            ),
            (
                "wf_sensitive",
                "민감 문의 상담원 이관",
                "분쟁·개인정보·고액 환불 문의를 즉시 상담원에게 전달합니다.",
                "안전 키워드 감지",
                "PAUSED",
                1,
                json.dumps(["키워드 감지", "우선순위 지정", "상담원 알림"], ensure_ascii=False),
                19,
                0,
                now,
            ),
        ]
        connection.executemany(
            "INSERT OR IGNORE INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", workflows
        )
        documents = [
            (
                "doc_shipping",
                "배송 및 출고 정책",
                "배송",
                "PUBLISHED",
                (
                    "결제 완료 후 평균 1영업일 이내 출고하며 배송은 "
                    "2~3영업일이 소요됩니다. 10만원 이상 주문은 무료배송입니다."
                ),
                "운영 정책",
                2,
                now,
            ),
            (
                "doc_returns",
                "교환·반품·환불 정책",
                "반품·환불",
                "PUBLISHED",
                (
                    "배송 완료 후 7일 이내 미사용 상품은 반품할 수 있습니다. "
                    "단순 변심 반품비는 3,000원입니다."
                ),
                "운영 정책",
                2,
                now,
            ),
            (
                "doc_products",
                "패션 상품 관리 가이드",
                "상품",
                "DRAFT",
                "사이즈별 재고와 소재, 세탁 방법을 상품 옵션 정보와 함께 확인합니다.",
                "내부 가이드",
                1,
                now,
            ),
        ]
        connection.executemany(
            "INSERT OR IGNORE INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?)",
            documents,
        )
        integrations = [
            (
                "int_gemini",
                "OpenRouter API",
                "OpenRouter",
                "AI 모델",
                "CONNECTED",
                "Model selected by Langfuse prompt config",
                now,
                now,
            ),
            (
                "int_langfuse",
                "Langfuse",
                "Langfuse",
                "프롬프트·관찰",
                "CONNECTED",
                "Japan region · production prompt",
                now,
                now,
            ),
            (
                "int_commerce",
                "Commerce API",
                "Everyday Market",
                "주문·상품",
                "CONNECTED",
                "http://localhost:8001",
                now,
                now,
            ),
            (
                "int_slack",
                "Discord Webhook",
                "Discord",
                "상담원 알림",
                "DISCONNECTED",
                "Webhook not configured",
                None,
                now,
            ),
        ]
        connection.executemany(
            "INSERT OR IGNORE INTO integrations VALUES(?,?,?,?,?,?,?,?)", integrations
        )
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        jobs = [
            (
                "job_stock_context",
                "wf_returns",
                None,
                "CONTEXT_MISSING",
                "상품 옵션별 재고 정보가 응답 컨텍스트에 없습니다.",
                json.dumps({"product_id": "prd_003", "size": "260"}, ensure_ascii=False),
                1,
                "PENDING",
                yesterday,
                yesterday,
            ),
            (
                "job_agent_alert",
                "wf_sensitive",
                None,
                "INTEGRATION_OFFLINE",
                "Discord Webhook이 설정되지 않았습니다.",
                json.dumps({"integration_id": "int_slack"}, ensure_ascii=False),
                0,
                "PENDING",
                now,
                now,
            ),
        ]
        connection.executemany(
            "INSERT OR IGNORE INTO failed_jobs VALUES(?,?,?,?,?,?,?,?,?,?)", jobs
        )
        connection.execute(
            """
            UPDATE integrations
            SET name = 'OpenRouter API',
                provider = 'OpenRouter',
                config_summary = 'Model selected by Langfuse prompt config',
                updated_at = ?
            WHERE id = 'int_gemini'
            """,
            (now,),
        )
        connection.execute(
            """
            UPDATE integrations
            SET name = 'Discord Webhook',
                provider = 'Discord',
                config_summary = 'Webhook not configured',
                updated_at = ?
            WHERE id = 'int_slack'
            """,
            (now,),
        )
        connection.execute(
            """
            UPDATE failed_jobs
            SET error_message = 'Discord Webhook이 설정되지 않았습니다.',
                updated_at = ?
            WHERE id = 'job_agent_alert'
            """,
            (now,),
        )
        connection.execute(
            "INSERT OR IGNORE INTO audit_logs VALUES(?,?,?,?,?,?,?)",
            (
                "audit_seed",
                "system",
                "WORKSPACE_INITIALIZED",
                "workspace",
                "everyday-market",
                "운영 워크스페이스 기본 데이터 생성",
                now,
            ),
        )

    def _list(self, table: str, order_by: str = "updated_at DESC") -> list[dict[str, Any]]:
        allowed = {
            "workflows",
            "knowledge_documents",
            "integrations",
            "failed_jobs",
            "audit_logs",
        }
        if table not in allowed:
            raise ValueError("Unsupported table")
        with closing(self.connect()) as connection:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
            result = [dict(row) for row in rows]
        for item in result:
            if "steps" in item:
                item["steps"] = json.loads(item["steps"])
            if "payload" in item:
                item["payload"] = json.loads(item["payload"])
        return result

    def list_workflows(self) -> list[dict[str, Any]]:
        return self._list("workflows")

    def list_documents(self) -> list[dict[str, Any]]:
        return self._list("knowledge_documents")

    def list_integrations(self) -> list[dict[str, Any]]:
        return self._list("integrations")

    def list_failed_jobs(self) -> list[dict[str, Any]]:
        return self._list("failed_jobs", "created_at DESC")

    def list_audit_logs(self) -> list[dict[str, Any]]:
        return self._list("audit_logs", "created_at DESC")

    def _audit(
        self,
        connection: Connection,
        action: str,
        target_type: str,
        target_id: str,
        detail: str,
        actor: str = "demo.admin",
    ) -> None:
        connection.execute(
            "INSERT INTO audit_logs VALUES(?,?,?,?,?,?,?)",
            (
                f"audit_{uuid4().hex[:12]}",
                actor,
                action,
                target_type,
                target_id,
                detail,
                utc_now(),
            ),
        )

    def update_workflow(self, workflow_id: str, status: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            connection.execute(
                "UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, workflow_id),
            )
            self._audit(
                connection,
                "WORKFLOW_STATUS_CHANGED",
                "workflow",
                workflow_id,
                f"{row['status']} → {status}",
            )
        return next(item for item in self.list_workflows() if item["id"] == workflow_id)

    def create_document(self, data: dict[str, Any]) -> dict[str, Any]:
        document_id = f"doc_{uuid4().hex[:12]}"
        content = str(data["content"])
        chunk_count = max(1, (len(content) + 399) // 400)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?,?)",
                (
                    document_id,
                    data["title"],
                    data["category"],
                    data.get("status", "DRAFT"),
                    content,
                    data.get("source", "직접 입력"),
                    chunk_count,
                    utc_now(),
                ),
            )
            self._audit(
                connection,
                "DOCUMENT_CREATED",
                "knowledge_document",
                document_id,
                str(data["title"]),
            )
        return next(item for item in self.list_documents() if item["id"] == document_id)

    def update_document(self, document_id: str, status: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE knowledge_documents SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), document_id),
            )
            self._audit(
                connection,
                "DOCUMENT_STATUS_CHANGED",
                "knowledge_document",
                document_id,
                f"{row['status']} → {status}",
            )
        return next(item for item in self.list_documents() if item["id"] == document_id)

    def check_integration(
        self, integration_id: str, *, discord_ready: bool = False
    ) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM integrations WHERE id = ?", (integration_id,)
            ).fetchone()
            if row is None:
                return None
            if integration_id == "int_slack":
                status = "CONNECTED" if discord_ready else "DISCONNECTED"
            else:
                status = "CONNECTED"
            connection.execute(
                """
                UPDATE integrations
                SET status = ?, last_checked_at = ?, updated_at = ? WHERE id = ?
                """,
                (status, utc_now(), utc_now(), integration_id),
            )
            self._audit(
                connection,
                "INTEGRATION_CHECKED",
                "integration",
                integration_id,
                f"연결 점검 결과: {status}",
            )
        return next(item for item in self.list_integrations() if item["id"] == integration_id)

    def retry_failed_job(
        self, job_id: str, *, discord_ready: bool = False
    ) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM failed_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            if row["error_code"] == "INTEGRATION_OFFLINE":
                status = "RESOLVED" if discord_ready else "FAILED"
            else:
                status = "RESOLVED"
            connection.execute(
                """
                UPDATE failed_jobs
                SET retry_count = retry_count + 1, status = ?, updated_at = ? WHERE id = ?
                """,
                (status, utc_now(), job_id),
            )
            self._audit(
                connection,
                "FAILED_JOB_RETRIED",
                "failed_job",
                job_id,
                f"재시도 결과: {status}",
            )
        return next(item for item in self.list_failed_jobs() if item["id"] == job_id)


ops_store = OpsStore()
ops_store.initialize()
