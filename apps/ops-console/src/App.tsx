import type {
  AuditLog,
  FailedJob,
  Inquiry,
  KnowledgeDocument,
  OpsIntegration,
  OpsWorkflow,
} from "@ai-ops/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  checkIntegration,
  createDocument,
  getAuditLogs,
  getDocuments,
  getFailedJobs,
  getInquiries,
  getInquiry,
  getIntegrations,
  getWorkflows,
  retryFailedJob,
  updateDocument,
  updateInquiry,
  updateWorkflow,
} from "./api";

type Page =
  | "dashboard"
  | "inquiries"
  | "workflows"
  | "knowledge"
  | "integrations"
  | "failed"
  | "audit";

const navigation: { id: Page; label: string }[] = [
  { id: "dashboard", label: "대시보드" },
  { id: "inquiries", label: "문의" },
  { id: "workflows", label: "워크플로" },
  { id: "knowledge", label: "지식 문서" },
  { id: "integrations", label: "연동" },
  { id: "failed", label: "실패 작업" },
  { id: "audit", label: "감사 로그" },
];

const categoryLabel: Record<string, string> = {
  DELIVERY: "배송",
  CANCEL: "취소",
  REFUND: "반품·환불",
  OTHER: "기타",
};
const statusLabel: Record<string, string> = {
  RECEIVED: "접수",
  AI_PROCESSING: "AI 처리 중",
  AUTO_RESOLVED: "AI 자동 해결",
  ESCALATED: "상담원 이관",
  RESOLVED: "해결",
};

export function App() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState<Page>("dashboard");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const inquiries = useQuery({
    queryKey: ["inquiries"],
    queryFn: getInquiries,
    refetchInterval: 10_000,
  });
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: getWorkflows });
  const documents = useQuery({ queryKey: ["documents"], queryFn: getDocuments });
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: getIntegrations,
  });
  const failedJobs = useQuery({ queryKey: ["failed-jobs"], queryFn: getFailedJobs });
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: getAuditLogs });
  const detail = useQuery({
    queryKey: ["inquiry", selectedId],
    queryFn: () => getInquiry(selectedId!),
    enabled: Boolean(selectedId),
  });

  const refreshAll = () => queryClient.invalidateQueries();
  const openInquiry = (id: string) => setSelectedId(id);
  const counts = {
    inquiries: inquiries.data?.length ?? 0,
    failed: failedJobs.data?.filter((item) => item.status !== "RESOLVED").length ?? 0,
  };

  return (
    <div className="app-shell">
      <Sidebar page={page} counts={counts} onNavigate={setPage} />
      {page === "dashboard" && (
        <Dashboard
          inquiries={inquiries.data ?? []}
          integrations={integrations.data ?? []}
          failedJobs={failedJobs.data ?? []}
          onOpenInquiry={openInquiry}
          onRefresh={refreshAll}
        />
      )}
      {page === "inquiries" && (
        <InquiriesPage
          inquiries={inquiries.data ?? []}
          loading={inquiries.isLoading}
          onOpen={openInquiry}
          onRefresh={refreshAll}
        />
      )}
      {page === "workflows" && (
        <WorkflowsPage workflows={workflows.data ?? []} loading={workflows.isLoading} />
      )}
      {page === "knowledge" && (
        <KnowledgePage documents={documents.data ?? []} loading={documents.isLoading} />
      )}
      {page === "integrations" && (
        <IntegrationsPage
          integrations={integrations.data ?? []}
          loading={integrations.isLoading}
        />
      )}
      {page === "failed" && (
        <FailedJobsPage jobs={failedJobs.data ?? []} loading={failedJobs.isLoading} />
      )}
      {page === "audit" && (
        <AuditPage logs={auditLogs.data ?? []} loading={auditLogs.isLoading} />
      )}
      {selectedId && (
        <InquiryDetail
          inquiry={detail.data}
          loading={detail.isLoading}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}

function Sidebar({
  page,
  counts,
  onNavigate,
}: {
  page: Page;
  counts: { inquiries: number; failed: number };
  onNavigate: (page: Page) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand"><span>AO</span><strong>AI Ops Studio</strong></div>
      <nav aria-label="운영 메뉴">
        {navigation.map((item) => (
          <button
            className={page === item.id ? "active" : ""}
            key={item.id}
            onClick={() => onNavigate(item.id)}
          >
            <span>{item.label}</span>
            {item.id === "inquiries" && counts.inquiries > 0 && <em>{counts.inquiries}</em>}
            {item.id === "failed" && counts.failed > 0 && <em className="warning">{counts.failed}</em>}
          </button>
        ))}
      </nav>
      <div className="workspace">
        <small>WORKSPACE</small><strong>Everyday Market</strong><span>Development</span>
      </div>
    </aside>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header>
      <div><p>{eyebrow}</p><h1>{title}</h1><span className="page-description">{description}</span></div>
      {action}
    </header>
  );
}

function Dashboard({
  inquiries,
  integrations,
  failedJobs,
  onOpenInquiry,
  onRefresh,
}: {
  inquiries: Inquiry[];
  integrations: OpsIntegration[];
  failedJobs: FailedJob[];
  onOpenInquiry: (id: string) => void;
  onRefresh: () => void;
}) {
  const stats = {
    total: inquiries.length,
    auto: inquiries.filter((item) => item.status === "AUTO_RESOLVED").length,
    escalated: inquiries.filter((item) => item.status === "ESCALATED").length,
    failed: failedJobs.filter((item) => item.status !== "RESOLVED").length,
  };
  const connected = integrations.filter((item) => item.status === "CONNECTED").length;
  return (
    <main>
      <PageHeader
        eyebrow="OVERVIEW"
        title="고객지원 운영 현황"
        description="AI 응대, 자동화와 외부 연동 상태를 한눈에 확인합니다."
        action={<button className="outline" onClick={onRefresh}>새로고침</button>}
      />
      <section className="stats">
        <article><span>전체 문의</span><strong>{stats.total}</strong><small>실제 저장 데이터</small></article>
        <article><span>AI 자동 해결</span><strong>{stats.auto}</strong><small className="positive">Gemini 응답 완료</small></article>
        <article><span>상담원 이관</span><strong>{stats.escalated}</strong><small>검토가 필요한 문의</small></article>
        <article><span>실패 작업</span><strong>{stats.failed}</strong><small>{stats.failed ? "재시도 필요" : "모두 정상"}</small></article>
      </section>
      <section className="content-grid">
        <article className="panel volume">
          <div className="panel-heading"><div><small>REALTIME</small><h2>문의 처리량</h2></div><span>최근 활동</span></div>
          <div className="chart" aria-label="문의 처리량 막대 차트">
            {[24, 36, 28, 48, 42, 60, 38, 68, 52, 76, 58, 46].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}
          </div>
          <div className="chart-labels"><span>00시</span><span>06시</span><span>12시</span><span>18시</span><span>24시</span></div>
        </article>
        <article className="panel health">
          <div className="panel-heading"><div><small>SYSTEM</small><h2>서비스 상태</h2></div><i className="status-dot" /></div>
          <ul>
            <li><span>Core API</span><strong>정상</strong></li>
            <li><span>외부 연동</span><strong>{connected}/{integrations.length}</strong></li>
            <li><span>Langfuse</span><strong>연결</strong></li>
            <li><span>Commerce API</span><strong>정상</strong></li>
          </ul>
        </article>
        <article className="panel inquiries">
          <div className="panel-heading"><div><small>INBOX</small><h2>최근 문의</h2></div><span>{inquiries.length}건</span></div>
          <div className="inquiry-list">
            {inquiries.slice(0, 5).map((item) => <InquiryRow key={item.id} inquiry={item} onClick={() => onOpenInquiry(item.id)} />)}
            {!inquiries.length && <p className="empty">아직 저장된 문의가 없습니다.</p>}
          </div>
        </article>
      </section>
    </main>
  );
}

function InquiriesPage({
  inquiries,
  loading,
  onOpen,
  onRefresh,
}: {
  inquiries: Inquiry[];
  loading: boolean;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const filtered = useMemo(
    () => inquiries.filter((item) => {
      const matchesQuery = !query || `${item.subject} ${item.customer_name} ${item.order_id ?? ""}`.toLowerCase().includes(query.toLowerCase());
      return matchesQuery && (status === "ALL" || item.status === status);
    }),
    [inquiries, query, status],
  );
  return (
    <main>
      <PageHeader
        eyebrow="INBOX"
        title="문의 관리"
        description="AI가 처리한 문의와 상담원 이관 건을 검색하고 상태를 관리합니다."
        action={<button className="outline" onClick={onRefresh}>새로고침</button>}
      />
      <section className="toolbar">
        <input aria-label="문의 검색" placeholder="고객, 주문번호, 문의 내용 검색" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="문의 상태" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="ALL">전체 상태</option>
          <option value="AUTO_RESOLVED">AI 자동 해결</option>
          <option value="ESCALATED">상담원 이관</option>
          <option value="RESOLVED">해결</option>
        </select>
      </section>
      <section className="panel table-panel">
        <div className="panel-heading"><div><small>RESULT</small><h2>문의 {filtered.length}건</h2></div></div>
        {loading && <p className="empty">문의 목록을 불러오는 중…</p>}
        <div className="inquiry-list">
          {filtered.map((item) => <InquiryRow key={item.id} inquiry={item} onClick={() => onOpen(item.id)} />)}
          {!loading && !filtered.length && <p className="empty">조건에 맞는 문의가 없습니다.</p>}
        </div>
      </section>
    </main>
  );
}

function InquiryRow({ inquiry, onClick }: { inquiry: Inquiry; onClick: () => void }) {
  return (
    <button onClick={onClick}>
      <span className={`category ${inquiry.category.toLowerCase()}`}>{categoryLabel[inquiry.category] ?? inquiry.category}</span>
      <span><strong>{inquiry.subject}</strong><small>{inquiry.customer_name} · {inquiry.order_id ?? "일반 문의"} · 메시지 {inquiry.message_count ?? 0}개</small></span>
      <em>{statusLabel[inquiry.status] ?? inquiry.status}</em>
    </button>
  );
}

function WorkflowsPage({ workflows, loading }: { workflows: OpsWorkflow[]; loading: boolean }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "ACTIVE" | "PAUSED" }) => updateWorkflow(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    },
  });
  return (
    <main>
      <PageHeader eyebrow="AUTOMATION" title="워크플로" description="문의 유형별 자동 처리 단계와 실행 상태를 관리합니다." />
      <section className="summary-strip">
        <span>전체 <strong>{workflows.length}</strong></span>
        <span>활성 <strong>{workflows.filter((item) => item.status === "ACTIVE").length}</strong></span>
        <span>총 성공 <strong>{workflows.reduce((sum, item) => sum + item.success_count, 0)}</strong></span>
      </section>
      <section className="card-grid">
        {loading && <p className="empty">워크플로를 불러오는 중…</p>}
        {workflows.map((workflow) => (
          <article className="management-card" key={workflow.id}>
            <div className="card-top"><span className={`state ${workflow.status.toLowerCase()}`}>{workflow.status === "ACTIVE" ? "활성" : "중지"}</span><small>v{workflow.version}</small></div>
            <h2>{workflow.name}</h2><p>{workflow.description}</p>
            <div className="trigger">TRIGGER · {workflow.trigger_type}</div>
            <ol className="steps">{workflow.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <footer><span>성공 {workflow.success_count} · 실패 {workflow.failure_count}</span><button disabled={mutation.isPending} onClick={() => mutation.mutate({ id: workflow.id, status: workflow.status === "ACTIVE" ? "PAUSED" : "ACTIVE" })}>{workflow.status === "ACTIVE" ? "일시 중지" : "활성화"}</button></footer>
          </article>
        ))}
      </section>
    </main>
  );
}

function KnowledgePage({ documents, loading }: { documents: KnowledgeDocument[]; loading: boolean }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState({ title: "", category: "배송", content: "", source: "직접 입력", status: "DRAFT" as "DRAFT" | "PUBLISHED" });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
  };
  const createMutation = useMutation({
    mutationFn: createDocument,
    onSuccess: () => {
      refresh();
      setShowForm(false);
      setForm({ title: "", category: "배송", content: "", source: "직접 입력", status: "DRAFT" });
    },
  });
  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "DRAFT" | "PUBLISHED" | "ARCHIVED" }) => updateDocument(id, status),
    onSuccess: refresh,
  });
  const filtered = documents.filter((item) => !query || `${item.title} ${item.category} ${item.content}`.toLowerCase().includes(query.toLowerCase()));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    createMutation.mutate(form);
  };
  return (
    <main>
      <PageHeader eyebrow="KNOWLEDGE BASE" title="지식 문서" description="AI 답변의 근거로 사용할 쇼핑몰 정책과 가이드를 관리합니다." action={<button className="primary" onClick={() => setShowForm((value) => !value)}>{showForm ? "취소" : "문서 추가"}</button>} />
      {showForm && (
        <form className="panel document-form" onSubmit={submit}>
          <label>문서 제목<input required minLength={2} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
          <label>분류<input required value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label>
          <label className="wide">내용<textarea required minLength={10} rows={6} value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} /></label>
          <label>출처<input value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })} /></label>
          <label>초기 상태<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as "DRAFT" | "PUBLISHED" })}><option value="DRAFT">초안</option><option value="PUBLISHED">게시</option></select></label>
          <button className="primary" disabled={createMutation.isPending}>{createMutation.isPending ? "저장 중…" : "저장"}</button>
        </form>
      )}
      <section className="toolbar"><input aria-label="지식 문서 검색" placeholder="문서 제목, 분류, 내용 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></section>
      <section className="document-list">
        {loading && <p className="empty">문서를 불러오는 중…</p>}
        {filtered.map((document) => (
          <article className="panel document-row" key={document.id}>
            <div><span className={`state ${document.status.toLowerCase()}`}>{document.status}</span><h2>{document.title}</h2><small>{document.category} · {document.source} · {document.chunk_count} chunks</small></div>
            <p>{document.content}</p>
            <div className="row-actions">
              {document.status !== "PUBLISHED" && <button onClick={() => statusMutation.mutate({ id: document.id, status: "PUBLISHED" })}>게시</button>}
              {document.status === "PUBLISHED" && <button onClick={() => statusMutation.mutate({ id: document.id, status: "DRAFT" })}>초안으로</button>}
              {document.status !== "ARCHIVED" && <button className="danger-text" onClick={() => statusMutation.mutate({ id: document.id, status: "ARCHIVED" })}>보관</button>}
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}

function IntegrationsPage({ integrations, loading }: { integrations: OpsIntegration[]; loading: boolean }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: checkIntegration,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    },
  });
  return (
    <main>
      <PageHeader eyebrow="CONNECTIONS" title="연동" description="AI 모델, 관찰 도구와 커머스 시스템의 연결 상태를 점검합니다." />
      <section className="integration-grid">
        {loading && <p className="empty">연동 정보를 불러오는 중…</p>}
        {integrations.map((integration) => (
          <article className="management-card integration-card" key={integration.id}>
            <div className="integration-logo">{integration.name.slice(0, 2).toUpperCase()}</div>
            <div className="card-top"><span className={`state ${integration.status.toLowerCase()}`}>{integration.status}</span><small>{integration.kind}</small></div>
            <h2>{integration.name}</h2><p>{integration.provider}</p>
            <code>{integration.config_summary}</code>
            <small>최근 점검: {integration.last_checked_at ? new Date(integration.last_checked_at).toLocaleString("ko-KR") : "점검 전"}</small>
            <button className="outline" disabled={mutation.isPending} onClick={() => mutation.mutate(integration.id)}>연결 점검</button>
          </article>
        ))}
      </section>
    </main>
  );
}

function FailedJobsPage({ jobs, loading }: { jobs: FailedJob[]; loading: boolean }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: retryFailedJob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["failed-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    },
  });
  return (
    <main>
      <PageHeader eyebrow="RECOVERY" title="실패 작업" description="자동화 실패 원인을 확인하고 안전하게 작업을 재시도합니다." />
      <section className="panel table-panel">
        <div className="data-table">
          <div className="data-row data-head"><span>상태</span><span>오류</span><span>연결 대상</span><span>재시도</span><span></span></div>
          {loading && <p className="empty">실패 작업을 불러오는 중…</p>}
          {jobs.map((job) => (
            <div className="data-row" key={job.id}>
              <span className={`state ${job.status.toLowerCase()}`}>{job.status}</span>
              <span><strong>{job.error_code}</strong><small>{job.error_message}</small></span>
              <span><code>{job.workflow_id ?? job.inquiry_id ?? "-"}</code></span>
              <span>{job.retry_count}회</span>
              <span><button disabled={mutation.isPending || job.status === "RESOLVED"} onClick={() => mutation.mutate(job.id)}>{job.status === "RESOLVED" ? "해결됨" : "재시도"}</button></span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function AuditPage({ logs, loading }: { logs: AuditLog[]; loading: boolean }) {
  const [query, setQuery] = useState("");
  const filtered = logs.filter((log) => !query || `${log.actor} ${log.action} ${log.target_id} ${log.detail}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <main>
      <PageHeader eyebrow="SECURITY" title="감사 로그" description="운영자가 수행한 상태 변경과 재시도 이력을 추적합니다." />
      <section className="toolbar"><input aria-label="감사 로그 검색" placeholder="작업, 대상, 담당자 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></section>
      <section className="panel audit-list">
        {loading && <p className="empty">감사 로그를 불러오는 중…</p>}
        {filtered.map((log) => (
          <article key={log.id}>
            <time>{new Date(log.created_at).toLocaleString("ko-KR")}</time>
            <span className="audit-action">{log.action}</span>
            <div><strong>{log.detail}</strong><small>{log.actor} · {log.target_type} · {log.target_id}</small></div>
          </article>
        ))}
      </section>
    </main>
  );
}

function InquiryDetail({ inquiry, loading, onClose }: { inquiry?: Inquiry; loading: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: (status: "ESCALATED" | "RESOLVED") => updateInquiry(inquiry!.id, status, note.trim() || undefined),
    onSuccess: () => {
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["inquiries"] });
      queryClient.invalidateQueries({ queryKey: ["inquiry", inquiry?.id] });
    },
  });
  return (
    <aside className="detail">
      <button className="close" onClick={onClose}>닫기</button>
      {loading && <p>문의 내용을 불러오는 중…</p>}
      {inquiry && (
        <>
          <small>INQUIRY DETAIL</small><h2>{inquiry.subject}</h2>
          <dl><dt>고객</dt><dd>{inquiry.customer_name}</dd><dt>상태</dt><dd>{statusLabel[inquiry.status] ?? inquiry.status}</dd><dt>분류</dt><dd>{categoryLabel[inquiry.category] ?? inquiry.category}</dd><dt>주문</dt><dd>{inquiry.order_id ?? "연결 없음"}</dd></dl>
          <div className="case-actions">
            <textarea aria-label="상담원 메모" rows={3} placeholder="고객에게 남길 답변 또는 처리 메모" value={note} onChange={(event) => setNote(event.target.value)} />
            <div><button disabled={mutation.isPending} onClick={() => mutation.mutate("ESCALATED")}>상담원 이관</button><button className="primary" disabled={mutation.isPending} onClick={() => mutation.mutate("RESOLVED")}>해결 처리</button></div>
          </div>
          <div className="conversation-log">
            <strong>고객 · AI 대화 로그</strong>
            {inquiry.messages?.map((message) => (
              <article className={message.role} key={message.id}>
                <small>{message.role === "user" ? "고객" : message.role === "agent" ? "상담원" : "AI"} · {new Date(message.created_at).toLocaleString("ko-KR")}</small>
                <div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                {message.model && <footer>{message.model} · prompt {message.prompt_version ?? "fallback"} · trace {message.trace_id?.slice(0, 12)}</footer>}
              </article>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
