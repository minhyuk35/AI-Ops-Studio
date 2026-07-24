import type {
  AuditLog,
  FailedJob,
  Inquiry,
  KnowledgeDocument,
  OpsIntegration,
  OpsWorkflow,
  ProductMetric,
  RevenueSummary,
} from "@ai-ops/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  checkIntegration,
  ConsoleProfile,
  createDocument,
  generateMonthlyReport,
  getAuditLogs,
  getCommerceInsight,
  getDocuments,
  getFailedJobs,
  getInquiries,
  getInquiry,
  getIntegrations,
  getPlatformDailyTraffic,
  getRevenueProducts,
  getRevenueSummary,
  getSellerDailyReport,
  getSellerMarketShare,
  getWorkflows,
  login,
  PlatformTrafficReport,
  retryFailedJob,
  SellerDailyReport,
  SellerMarketShareReport,
  updateDocument,
  updateInquiry,
  updateWorkflow,
} from "./api";

type Page =
  | "dashboard"
  | "seller-dashboard"
  | "inquiries"
  | "workflows"
  | "knowledge"
  | "integrations"
  | "failed"
  | "audit"
  | "revenue"
  | "report"
  | "platform-traffic"
  | "market-share";

const ADMIN_NAVIGATION: { id: Page; label: string }[] = [
  { id: "dashboard", label: "대시보드" },
  { id: "inquiries", label: "문의" },
  { id: "revenue", label: "매출 분석" },
  { id: "report", label: "AI 리포트" },
  { id: "platform-traffic", label: "플랫폼 트래픽" },
  { id: "market-share", label: "판매자 비교" },
  { id: "workflows", label: "워크플로" },
  { id: "knowledge", label: "지식 문서" },
  { id: "integrations", label: "연동" },
  { id: "failed", label: "실패 작업" },
  { id: "audit", label: "감사 로그" },
];

const SELLER_NAVIGATION: { id: Page; label: string }[] = [
  { id: "seller-dashboard", label: "대시보드" },
  { id: "inquiries", label: "문의" },
];

const SESSION_KEY = "ops-console-session";

interface Session {
  token: string;
  profile: ConsoleProfile;
}

function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

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

const currentPeriod = () => new Date().toISOString().slice(0, 7);

export function App() {
  const [session, setSession] = useState<Session | null>(loadSession);

  const handleLogin = (next: Session) => {
    localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    setSession(next);
  };
  const handleLogout = () => {
    localStorage.removeItem(SESSION_KEY);
    setSession(null);
  };

  if (!session) return <LoginPage onLogin={handleLogin} />;
  if (session.profile.role !== "SELLER" && session.profile.role !== "ADMIN") {
    return (
      <div className="login-shell">
        <div className="login-card">
          <div className="brand"><span>AO</span><strong>AI Ops Studio</strong></div>
          <p className="empty">판매자 또는 관리자 계정으로 로그인해주세요.</p>
          <button className="outline" onClick={handleLogout}>다시 로그인</button>
        </div>
      </div>
    );
  }
  return <ConsoleShell session={session} onLogout={handleLogout} />;
}

function LoginPage({ onLogin }: { onLogin: (session: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (data) => onLogin({ token: data.access_token, profile: data.customer }),
    onError: (err: Error) => setError(err.message),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    mutation.mutate();
  };
  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div className="brand"><span>AO</span><strong>AI Ops Studio</strong></div>
        <p className="page-description">판매자 콘솔 · 관리자 콘솔 로그인</p>
        <label>이메일<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>비밀번호<input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={mutation.isPending}>
          {mutation.isPending ? "로그인 중…" : "로그인"}
        </button>
        <p className="empty">
          테스트 계정: seller@test.com / test1234 (판매자) · admin@test.com / test1234 (관리자)
        </p>
      </form>
    </div>
  );
}

function ConsoleShell({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const { token, profile } = session;
  const isAdmin = profile.role === "ADMIN";
  const navigation = isAdmin ? ADMIN_NAVIGATION : SELLER_NAVIGATION;
  const queryClient = useQueryClient();
  const [page, setPage] = useState<Page>(isAdmin ? "dashboard" : "seller-dashboard");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [period, setPeriod] = useState(currentPeriod);
  const orgId = profile.organization?.id;
  const inquiries = useQuery({
    queryKey: isAdmin ? ["inquiries"] : ["inquiries", orgId],
    queryFn: () => getInquiries(isAdmin ? undefined : orgId, isAdmin ? undefined : token),
    refetchInterval: 10_000,
    enabled: isAdmin || Boolean(orgId),
  });
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: getWorkflows });
  const documents = useQuery({ queryKey: ["documents"], queryFn: getDocuments });
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: getIntegrations,
  });
  const failedJobs = useQuery({ queryKey: ["failed-jobs"], queryFn: getFailedJobs });
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: getAuditLogs });
  const revenueSummary = useQuery({
    queryKey: ["revenue-summary", period],
    queryFn: () => getRevenueSummary(period),
    enabled: page === "revenue",
  });
  const revenueProducts = useQuery({
    queryKey: ["revenue-products", period],
    queryFn: () => getRevenueProducts(period),
    enabled: page === "revenue",
  });
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
      <Sidebar
        page={page}
        counts={counts}
        onNavigate={setPage}
        navigation={navigation}
        workspaceName={isAdmin ? "Everyday Market" : profile.organization?.name ?? profile.name}
        workspaceMeta={isAdmin ? "관리자" : "판매자"}
        onLogout={onLogout}
      />
      {page === "seller-dashboard" && orgId && (
        <SellerDashboardPage token={token} orgId={orgId} />
      )}
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
      {page === "revenue" && (
        <RevenuePage
          summary={revenueSummary.data}
          products={revenueProducts.data ?? []}
          loading={revenueSummary.isLoading || revenueProducts.isLoading}
          period={period}
          onPeriodChange={setPeriod}
        />
      )}
      {page === "report" && <ReportPage period={period} onPeriodChange={setPeriod} />}
      {page === "platform-traffic" && <PlatformTrafficPage token={token} />}
      {page === "market-share" && <MarketSharePage token={token} period={period} onPeriodChange={setPeriod} />}
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
  navigation,
  workspaceName,
  workspaceMeta,
  onLogout,
}: {
  page: Page;
  counts: { inquiries: number; failed: number };
  onNavigate: (page: Page) => void;
  navigation: { id: Page; label: string }[];
  workspaceName: string;
  workspaceMeta: string;
  onLogout: () => void;
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
        <small>WORKSPACE</small><strong>{workspaceName}</strong><span>{workspaceMeta}</span>
        <button className="outline" onClick={onLogout}>로그아웃</button>
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
        <article><span>AI 자동 해결</span><strong>{stats.auto}</strong><small className="positive">OpenRouter 응답 완료</small></article>
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

const wonFormatter = new Intl.NumberFormat("ko-KR");
const formatWon = (value: number) => `₩${wonFormatter.format(value)}`;
const formatPct = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${value > 0 ? "+" : ""}${value}%`;

function RevenuePage({
  summary,
  products,
  loading,
  period,
  onPeriodChange,
}: {
  summary?: RevenueSummary;
  products: ProductMetric[];
  loading: boolean;
  period: string;
  onPeriodChange: (period: string) => void;
}) {
  const [sort, setSort] = useState<"revenue" | "units_sold" | "refund_rate">("revenue");
  const sorted = useMemo(() => {
    const withData = [...products];
    withData.sort((a, b) => {
      if (sort === "refund_rate") return (b.refund_rate ?? -1) - (a.refund_rate ?? -1);
      return b[sort] - a[sort];
    });
    return withData;
  }, [products, sort]);
  const insightMutation = useMutation({
    mutationFn: () => getCommerceInsight(period),
  });

  return (
    <main>
      <PageHeader
        eyebrow="COMMERCE"
        title="매출 분석"
        description="코드가 계산한 매출·상품·환불 지표입니다. AI는 이 숫자를 나중에 해석만 합니다."
        action={
          <input
            className="period-input"
            aria-label="분석 기간"
            type="month"
            value={period}
            onChange={(event) => onPeriodChange(event.target.value)}
          />
        }
      />
      {loading && <p className="empty">매출 데이터를 불러오는 중…</p>}
      {summary && (
        <section className="stats revenue">
          <RevenueStat label="총결제액" value={summary.gross_revenue} change={summary.change.gross_revenue_pct} />
          <RevenueStat label="취소·환불액" value={summary.refund_amount} />
          <RevenueStat label="순매출" value={summary.net_revenue} change={summary.change.net_revenue_pct} />
          <RevenueStat label="주문 수" value={summary.order_count} change={summary.change.order_count_pct} unit="건" />
          <RevenueStat label="객단가" value={summary.average_order_value} change={summary.change.average_order_value_pct} />
        </section>
      )}
      <section className="panel insight-panel">
        <div className="panel-heading">
          <div><small>AI · commerce-insight</small><h2>AI 인사이트</h2></div>
          <button
            className="primary"
            disabled={insightMutation.isPending}
            onClick={() => insightMutation.mutate()}
          >
            {insightMutation.isPending ? "분석 중…" : "AI 인사이트 생성"}
          </button>
        </div>
        {insightMutation.isError && <p className="empty">인사이트 생성에 실패했습니다.</p>}
        {insightMutation.isSuccess && (
          <>
            <div className="markdown-body"><ReactMarkdown>{insightMutation.data.insight}</ReactMarkdown></div>
            <footer className="insight-footer">
              {insightMutation.data.model} · prompt {insightMutation.data.prompt_source === "langfuse" ? insightMutation.data.prompt_version ?? "langfuse" : "fallback"}
            </footer>
          </>
        )}
        {!insightMutation.isSuccess && !insightMutation.isPending && !insightMutation.isError && (
          <p className="empty">숫자는 코드가 이미 계산했습니다. 버튼을 누르면 AI가 변화와 이상치를 해석합니다.</p>
        )}
      </section>
      <section className="panel table-panel revenue-table">
        <div className="panel-heading">
          <div><small>PRODUCTS</small><h2>상품별 판매·환불</h2></div>
          <select aria-label="정렬 기준" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
            <option value="revenue">매출순</option>
            <option value="units_sold">판매량순(인기)</option>
            <option value="refund_rate">환불률순</option>
          </select>
        </div>
        <div className="data-table">
          <div className="data-row data-head">
            <span>상품</span><span>판매수량</span><span>매출</span><span>환불수량</span><span>환불액</span><span>환불률</span>
          </div>
          {sorted.map((product) => (
            <div className="data-row" key={product.product_id}>
              <span>{product.product_name}</span>
              <span>{product.units_sold}개</span>
              <span>{formatWon(product.revenue)}</span>
              <span>{product.refund_units}개</span>
              <span>{formatWon(product.refund_amount)}</span>
              <span className={product.refund_rate !== null && product.refund_rate >= 0.2 ? "refund-high" : ""}>
                {product.refund_rate === null ? "—" : `${Math.round(product.refund_rate * 100)}%`}
                {product.units_sold > 0 && product.units_sold < 3 && <small> · 표본 적음</small>}
              </span>
            </div>
          ))}
          {!loading && !sorted.length && <p className="empty">이 기간에는 상품 데이터가 없습니다.</p>}
        </div>
      </section>
    </main>
  );
}

function RevenueStat({
  label,
  value,
  change,
  unit,
}: {
  label: string;
  value: number;
  change?: number | null;
  unit?: string;
}) {
  return (
    <article>
      <span>{label}</span>
      <strong>{unit ? `${value}${unit}` : formatWon(value)}</strong>
      {change !== undefined && (
        <small className={change === null ? "" : change >= 0 ? "positive" : "negative"}>
          전월 대비 {formatPct(change)}
        </small>
      )}
    </article>
  );
}

function ReportPage({
  period,
  onPeriodChange,
}: {
  period: string;
  onPeriodChange: (period: string) => void;
}) {
  const [sendDiscord, setSendDiscord] = useState(false);
  const reportMutation = useMutation({
    mutationFn: () => generateMonthlyReport(period, sendDiscord),
  });

  return (
    <main>
      <PageHeader
        eyebrow="AI · commerce-monthly-report"
        title="AI 리포트"
        description="매출 지표와 AI 인사이트를 하나의 월간 보고서로 정리하고, 원하면 Discord로 전송합니다."
        action={
          <input
            className="period-input"
            aria-label="리포트 기간"
            type="month"
            value={period}
            onChange={(event) => onPeriodChange(event.target.value)}
          />
        }
      />
      <section className="panel report-panel">
        <div className="panel-heading">
          <div><small>REPORT</small><h2>{period} 월간 리포트</h2></div>
          <div className="report-actions">
            <label className="discord-toggle">
              <input
                type="checkbox"
                checked={sendDiscord}
                onChange={(event) => setSendDiscord(event.target.checked)}
              />
              Discord로 전송
            </label>
            <button
              className="primary"
              disabled={reportMutation.isPending}
              onClick={() => reportMutation.mutate()}
            >
              {reportMutation.isPending ? "생성 중…" : "리포트 생성"}
            </button>
          </div>
        </div>
        {reportMutation.isError && <p className="empty">리포트 생성에 실패했습니다.</p>}
        {reportMutation.isSuccess && (
          <>
            <div className="markdown-body"><ReactMarkdown>{reportMutation.data.report}</ReactMarkdown></div>
            <footer className="insight-footer">
              {reportMutation.data.model} · prompt {reportMutation.data.prompt_source === "langfuse" ? reportMutation.data.prompt_version ?? "langfuse" : "fallback"}
              {" · "}
              {reportMutation.data.discord_sent ? "Discord 전송 완료" : sendDiscord ? "Discord 전송 안 됨 (웹훅 미설정)" : "Discord 미전송"}
            </footer>
          </>
        )}
        {!reportMutation.isSuccess && !reportMutation.isPending && !reportMutation.isError && (
          <p className="empty">버튼을 누르면 이번 기간의 인사이트를 먼저 생성한 뒤 리포트로 편집합니다.</p>
        )}
      </section>
    </main>
  );
}

function SellerDashboardPage({ token, orgId }: { token: string; orgId: string }) {
  const query = useQuery({
    queryKey: ["seller-daily-report", orgId],
    queryFn: () => getSellerDailyReport(token, orgId, false),
  });
  const discordMutation = useMutation({
    mutationFn: () => getSellerDailyReport(token, orgId, true),
  });
  const report: SellerDailyReport | undefined = discordMutation.data ?? query.data;
  const snapshot = report?.snapshot;

  return (
    <main>
      <PageHeader
        eyebrow="AI · daily-seller-report"
        title={report ? `${report.org_name} 오늘의 대시보드` : "오늘의 대시보드"}
        description="어제까지의 조회·판매·환불·재고를 코드가 집계하고, AI가 마지막에 재입고 제안을 덧붙입니다."
        action={
          <button
            className="primary"
            disabled={discordMutation.isPending || query.isLoading}
            onClick={() => discordMutation.mutate()}
          >
            {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
          </button>
        }
      />
      {query.isLoading && <p className="empty">오늘의 데이터를 불러오는 중…</p>}
      {query.isError && <p className="empty">데이터를 불러오지 못했습니다.</p>}
      {snapshot && (
        <>
          <section className="stats revenue">
            <article><span>총결제액</span><strong>{formatWon(snapshot.revenue.gross_revenue)}</strong></article>
            <article><span>환불액</span><strong>{formatWon(snapshot.revenue.refund_amount)}</strong></article>
            <article><span>순매출</span><strong>{formatWon(snapshot.revenue.net_revenue)}</strong></article>
            <article><span>주문 수</span><strong>{snapshot.revenue.order_count}건</strong></article>
            <article><span>날짜</span><strong>{snapshot.date}</strong></article>
          </section>
          <section className="grid two" style={{ marginTop: 16 }}>
            <div className="card">
              <h3>오늘의 조회</h3>
              <p>
                최다 조회: <strong>{snapshot.highlights.most_viewed?.product_name ?? "없음"}</strong>
                {snapshot.highlights.most_viewed && ` (${snapshot.highlights.most_viewed.views}회)`}
              </p>
              <p>
                최소 조회: <strong>{snapshot.highlights.least_viewed?.product_name ?? "없음"}</strong>
                {snapshot.highlights.least_viewed && ` (${snapshot.highlights.least_viewed.views}회)`}
              </p>
            </div>
            <div className="card">
              <h3>오늘의 판매·환불</h3>
              <p>
                최다 판매: <strong>{snapshot.highlights.most_purchased?.product_name ?? "없음"}</strong>
                {snapshot.highlights.most_purchased && ` (${snapshot.highlights.most_purchased.units_sold}개)`}
              </p>
              <p>
                최다 환불: <strong>{snapshot.highlights.most_refunded?.product_name ?? "없음"}</strong>
                {snapshot.highlights.most_refunded && ` (${snapshot.highlights.most_refunded.refund_units}개)`}
              </p>
            </div>
          </section>
          {(snapshot.highlights.out_of_stock.length > 0 || snapshot.highlights.low_stock.length > 0) && (
            <section className="callout-warning" style={{ marginTop: 16 }}>
              {snapshot.highlights.out_of_stock.length > 0 && (
                <p><strong>품절:</strong> {snapshot.highlights.out_of_stock.map((p) => p.product_name).join(", ")}</p>
              )}
              {snapshot.highlights.low_stock.length > 0 && (
                <p><strong>재고 부족:</strong> {snapshot.highlights.low_stock.map((p) => `${p.product_name}(${p.stock}개)`).join(", ")}</p>
              )}
            </section>
          )}
          <section className="panel table-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>PRODUCTS</small><h2>상품별 오늘 활동</h2></div></div>
            <div className="data-table">
              <div className="data-row data-head">
                <span>상품</span><span>조회</span><span>판매</span><span>환불</span><span>재고</span>
              </div>
              {snapshot.products.map((p) => (
                <div className="data-row" key={p.product_id}>
                  <span>{p.product_name}</span>
                  <span>{p.views}회</span>
                  <span>{p.units_sold}개 · {formatWon(p.revenue)}</span>
                  <span>{p.refund_units}개</span>
                  <span className={p.stock === 0 ? "refund-high" : ""}>{p.stock}개</span>
                </div>
              ))}
            </div>
          </section>
          <section className="panel insight-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>AI</small><h2>AI 리포트 · 재입고 제안</h2></div></div>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="insight-footer">
              {report!.model} · prompt {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"}
              {" · "}
              {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}
            </footer>
          </section>
        </>
      )}
    </main>
  );
}

function PlatformTrafficPage({ token }: { token: string }) {
  const query = useQuery({
    queryKey: ["platform-daily-traffic"],
    queryFn: () => getPlatformDailyTraffic(token, false),
  });
  const discordMutation = useMutation({
    mutationFn: () => getPlatformDailyTraffic(token, true),
  });
  const report: PlatformTrafficReport | undefined = discordMutation.data ?? query.data;
  const snapshot = report?.snapshot;

  return (
    <main>
      <PageHeader
        eyebrow="AI · platform-daily-traffic · 관리자 전용"
        title="플랫폼 트래픽"
        description="사이트 전체(모든 판매자 상품 포함) 오늘 조회수를 코드가 집계하고, AI가 해석합니다. 판매자 콘솔에는 노출되지 않습니다."
        action={
          <button
            className="primary"
            disabled={discordMutation.isPending || query.isLoading}
            onClick={() => discordMutation.mutate()}
          >
            {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
          </button>
        }
      />
      {query.isLoading && <p className="empty">오늘의 트래픽을 불러오는 중…</p>}
      {query.isError && <p className="empty">데이터를 불러오지 못했습니다.</p>}
      {snapshot && (
        <>
          <section className="stats">
            <article><span>전체 조회수</span><strong>{snapshot.total_views}</strong></article>
            <article><span>날짜</span><strong>{snapshot.date}</strong></article>
          </section>
          <section className="grid two" style={{ marginTop: 16 }}>
            <div className="card">
              <h3>상점별 조회수 순위</h3>
              {snapshot.store_ranking.slice(0, 8).map((row) => (
                <p key={row.org_name}>{row.org_name}: <strong>{row.views}회</strong></p>
              ))}
            </div>
            <div className="card">
              <h3>가장 적게 조회된 상품</h3>
              {snapshot.least_viewed_products.slice(0, 5).map((row) => (
                <p key={row.product_id}>{row.product_name} ({row.org_name}): <strong>{row.views}회</strong></p>
              ))}
            </div>
          </section>
          <section className="panel table-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>TOP</small><h2>가장 많이 조회된 상품 (전체 판매자)</h2></div></div>
            <div className="data-table">
              <div className="data-row data-head"><span>상품</span><span>상점</span><span>조회수</span></div>
              {snapshot.top_products.map((row) => (
                <div className="data-row" key={row.product_id}>
                  <span>{row.product_name}</span>
                  <span>{row.org_name}</span>
                  <span>{row.views}회</span>
                </div>
              ))}
            </div>
          </section>
          <section className="panel insight-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>AI</small><h2>AI 리포트</h2></div></div>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="insight-footer">
              {report!.model} · prompt {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"}
              {" · "}
              {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}
            </footer>
          </section>
        </>
      )}
    </main>
  );
}

function MarketSharePage({
  token,
  period,
  onPeriodChange,
}: {
  token: string;
  period: string;
  onPeriodChange: (period: string) => void;
}) {
  const query = useQuery({
    queryKey: ["seller-market-share", period],
    queryFn: () => getSellerMarketShare(token, false, period),
  });
  const discordMutation = useMutation({
    mutationFn: () => getSellerMarketShare(token, true, period),
  });
  const report: SellerMarketShareReport | undefined = discordMutation.data ?? query.data;
  const snapshot = report?.snapshot;
  const planLabel: Record<string, string> = { FREE: "무료 입점", BASIC: "Basic", PRO: "Pro", BUSINESS: "Business" };

  return (
    <main>
      <PageHeader
        eyebrow="AI · seller-market-share-report · 관리자 전용"
        title="판매자 매출 비교"
        description="판매자 매출액이 아니라, 수수료+플랜 요금으로 이 사이트가 실제로 버는 돈을 판매자별로 비교합니다."
        action={
          <div className="report-actions">
            <input
              className="period-input"
              aria-label="비교 기간"
              type="month"
              value={period}
              onChange={(event) => onPeriodChange(event.target.value)}
            />
            <button
              className="primary"
              disabled={discordMutation.isPending || query.isLoading}
              onClick={() => discordMutation.mutate()}
            >
              {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
            </button>
          </div>
        }
      />
      {query.isLoading && <p className="empty">데이터를 불러오는 중…</p>}
      {query.isError && <p className="empty">데이터를 불러오지 못했습니다.</p>}
      {snapshot && (
        <>
          <section className="stats">
            <article><span>플랫폼 전체 매출</span><strong>{formatWon(snapshot.total_platform_revenue)}</strong><small>수수료+플랜 요금 합계</small></article>
            <article><span>플랫폼 기본 상품 비중</span><strong>{snapshot.platform_default_share_pct ?? "—"}%</strong></article>
            <article><span>이번 달</span><strong>{snapshot.period}</strong></article>
            <article><span>지난 달</span><strong>{snapshot.previous_period}</strong></article>
          </section>
          <section className="panel table-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>SELLERS</small><h2>판매자별 플랫폼 매출 점유율</h2></div></div>
            <div className="data-table">
              <div className="data-row data-head">
                <span>판매자</span><span>플랜</span><span>판매액(GMV)</span><span>수수료+플랜</span><span>점유율</span>
              </div>
              {snapshot.sellers.map((seller) => (
                <div className="data-row" key={seller.org_id}>
                  <span>{seller.org_name}</span>
                  <span>{planLabel[seller.plan] ?? seller.plan}</span>
                  <span>{formatWon(seller.gross_revenue)}</span>
                  <span>{formatWon(seller.commission_revenue)} + {formatWon(seller.plan_fee)} = {formatWon(seller.platform_contribution)}</span>
                  <span>
                    {seller.share_pct ?? "—"}%
                    {seller.previous_share_pct !== null && seller.share_pct !== null && (
                      <small> ({seller.share_pct >= seller.previous_share_pct ? "+" : ""}{Math.round((seller.share_pct - seller.previous_share_pct) * 10) / 10}%p)</small>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </section>
          <section className="panel insight-panel" style={{ marginTop: 16 }}>
            <div className="panel-heading"><div><small>AI</small><h2>AI 리포트</h2></div></div>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="insight-footer">
              {report!.model} · prompt {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"}
              {" · "}
              {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}
            </footer>
          </section>
        </>
      )}
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
