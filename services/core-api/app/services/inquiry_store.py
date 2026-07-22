import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas.ai import AIReplyRequest, AIReplyResponse


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class InquiryStore:
    def __init__(self) -> None:
        configured = os.getenv("SUPPORT_DB_PATH", "data/support.db")
        self.path = Path(configured)
        if not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inquiries (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT,
                    customer_name TEXT NOT NULL,
                    order_id TEXT,
                    product_id TEXT,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    session_id TEXT,
                    organization_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    inquiry_id TEXT NOT NULL UNIQUE REFERENCES inquiries(id),
                    session_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    prompt_source TEXT,
                    prompt_version TEXT,
                    trace_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inquiry_events (
                    id TEXT PRIMARY KEY,
                    inquiry_id TEXT NOT NULL REFERENCES inquiries(id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_exchange(self, request: AIReplyRequest, response: AIReplyResponse) -> tuple[str, str]:
        now = utc_now()
        inquiry_id = request.inquiry_id or f"inq_{uuid4().hex[:12]}"
        trace_id = response.trace_id or request.request_id
        with closing(self.connect()) as connection:
            inquiry = connection.execute(
                "SELECT id FROM inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if inquiry is None:
                status = "ESCALATED" if response.requires_human else "AI_PROCESSING"
                connection.execute(
                    """
                    INSERT INTO inquiries(
                        id, customer_id, customer_name, order_id, product_id, category,
                        status, channel, subject, session_id, organization_id,
                        created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        inquiry_id,
                        request.user_id,
                        "데모 고객",
                        request.order_id,
                        request.product_id,
                        self._classify(request.question),
                        status,
                        request.channel,
                        request.question[:100],
                        request.session_id,
                        request.organization_id,
                        now,
                        now,
                    ),
                )
                conversation_id = f"conv_{uuid4().hex[:12]}"
                connection.execute(
                    """
                    INSERT INTO conversations(id, inquiry_id, session_id, created_at)
                    VALUES(?,?,?,?)
                    """,
                    (conversation_id, inquiry_id, request.session_id, now),
                )
                connection.execute(
                    "INSERT INTO inquiry_events VALUES(?,?,?,?,?,?)",
                    (
                        f"evt_{uuid4().hex[:12]}",
                        inquiry_id,
                        "CREATED",
                        "customer",
                        "문의 생성",
                        now,
                    ),
                )
            else:
                conversation_id = connection.execute(
                    "SELECT id FROM conversations WHERE inquiry_id = ?", (inquiry_id,)
                ).fetchone()["id"]
            connection.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"msg_{uuid4().hex[:12]}",
                    conversation_id,
                    "user",
                    request.question,
                    None,
                    None,
                    None,
                    trace_id,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"msg_{uuid4().hex[:12]}",
                    conversation_id,
                    "assistant",
                    response.answer,
                    response.model,
                    response.prompt_source,
                    response.prompt_version,
                    trace_id,
                    utc_now(),
                ),
            )
            final_status = "ESCALATED" if response.requires_human else "AUTO_RESOLVED"
            connection.execute(
                "UPDATE inquiries SET status = ?, updated_at = ? WHERE id = ?",
                (final_status, utc_now(), inquiry_id),
            )
            if response.requires_human:
                connection.execute(
                    "INSERT INTO inquiry_events VALUES(?,?,?,?,?,?)",
                    (
                        f"evt_{uuid4().hex[:12]}",
                        inquiry_id,
                        "ESCALATED",
                        "ai",
                        "AI 안전 규칙에 따라 상담원에게 이관",
                        utc_now(),
                    ),
                )
            connection.commit()
        return inquiry_id, conversation_id

    def list_inquiries(self) -> list[dict[str, object]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT i.*,
                       (SELECT COUNT(*) FROM messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE c.inquiry_id = i.id) message_count,
                       (SELECT content FROM messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE c.inquiry_id = i.id ORDER BY m.created_at DESC LIMIT 1) last_message
                FROM inquiries i ORDER BY i.updated_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_inquiry(self, inquiry_id: str) -> dict[str, object] | None:
        with closing(self.connect()) as connection:
            inquiry = connection.execute(
                "SELECT * FROM inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if inquiry is None:
                return None
            result = dict(inquiry)
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE inquiry_id = ?", (inquiry_id,)
            ).fetchone()
            result["conversation"] = dict(conversation) if conversation else None
            result["messages"] = []
            if conversation:
                result["messages"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                        (conversation["id"],),
                    ).fetchall()
                ]
            result["events"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM inquiry_events WHERE inquiry_id = ? ORDER BY created_at",
                    (inquiry_id,),
                ).fetchall()
            ]
            return result

    def list_customer_inquiries(self, customer_id: str) -> list[dict[str, object]]:
        return [
            inquiry
            for inquiry in self.list_inquiries()
            if inquiry.get("customer_id") == customer_id
        ]

    def update_status(
        self, inquiry_id: str, status: str, note: str | None = None
    ) -> dict[str, object] | None:
        now = utc_now()
        with closing(self.connect()) as connection:
            inquiry = connection.execute(
                "SELECT * FROM inquiries WHERE id = ?", (inquiry_id,)
            ).fetchone()
            if inquiry is None:
                return None
            connection.execute(
                "UPDATE inquiries SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, inquiry_id),
            )
            connection.execute(
                "INSERT INTO inquiry_events VALUES(?,?,?,?,?,?)",
                (
                    f"evt_{uuid4().hex[:12]}",
                    inquiry_id,
                    "STATUS_CHANGED",
                    "demo.admin",
                    f"{inquiry['status']} → {status}",
                    now,
                ),
            )
            if note:
                conversation = connection.execute(
                    "SELECT id FROM conversations WHERE inquiry_id = ?", (inquiry_id,)
                ).fetchone()
                if conversation:
                    connection.execute(
                        "INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            f"msg_{uuid4().hex[:12]}",
                            conversation["id"],
                            "agent",
                            note,
                            None,
                            None,
                            None,
                            None,
                            now,
                        ),
                    )
            connection.commit()
        return self.get_inquiry(inquiry_id)

    @staticmethod
    def _classify(question: str) -> str:
        if any(word in question for word in ("배송", "도착", "택배")):
            return "DELIVERY"
        if any(word in question for word in ("취소", "철회")):
            return "CANCEL"
        if any(word in question for word in ("환불", "반품", "교환")):
            return "REFUND"
        return "OTHER"


inquiry_store = InquiryStore()
inquiry_store.initialize()
