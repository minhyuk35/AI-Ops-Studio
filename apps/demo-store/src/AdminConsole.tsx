import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  AuthResponse,
  Coupon,
  CouponInput,
  createCoupon,
  getAdminCoupons,
  getOrganizations,
  getPlatformDailyTraffic,
  getSellerMarketShare,
  OrganizationSummary,
  PlatformTrafficReport,
  SellerMarketShareReport,
  updateCouponActive,
  updateOrganizationStatus,
} from "./api";
import { PageHeader, won } from "./console-shared";

export default function AdminConsolePage({
  auth,
  onBack,
  onError,
}: {
  auth: AuthResponse;
  onBack: () => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"orgs" | "traffic" | "share" | "coupons">("orgs");
  const organizations = useQuery({
    queryKey: ["admin-organizations"],
    queryFn: () => getOrganizations(auth.access_token),
    enabled: tab === "orgs",
  });
  const toggleStatus = useMutation({
    mutationFn: (org: OrganizationSummary) =>
      updateOrganizationStatus(auth.access_token, org.id, org.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-organizations"] }),
    onError: (error: Error) => onError(error.message),
  });

  return (
    <main className="store-section profile-page admin-console console-page">
      <PageHeader eyebrow="ADMIN CONSOLE" title="총관리자 콘솔" onBack={onBack} />
      <div className="console-tabs">
        <button className={tab === "orgs" ? "active" : ""} onClick={() => setTab("orgs")}>판매자 관리</button>
        <button className={tab === "traffic" ? "active" : ""} onClick={() => setTab("traffic")}>플랫폼 트래픽</button>
        <button className={tab === "share" ? "active" : ""} onClick={() => setTab("share")}>매출 비교</button>
        <button className={tab === "coupons" ? "active" : ""} onClick={() => setTab("coupons")}>쿠폰 관리</button>
      </div>

      {tab === "orgs" && (
        <>
          {organizations.isLoading && <p className="empty">불러오는 중…</p>}
          <div className="admin-org-list">
            {organizations.data?.map((org) => (
              <article className="admin-org-row" key={org.id}>
                <div>
                  <span className={`state ${org.status === "ACTIVE" ? "active" : "disconnected"}`}>{org.status}</span>
                  <h3>{org.name}</h3>
                  <small>{org.category} · 상품 {org.product_count}개 · 대표 {org.owner?.name} ({org.owner?.email})</small>
                </div>
                <button
                  className={org.status === "ACTIVE" ? "danger-button" : "primary dark"}
                  disabled={toggleStatus.isPending}
                  onClick={() => toggleStatus.mutate(org)}
                >
                  {org.status === "ACTIVE" ? "정지" : "활성화"}
                </button>
              </article>
            ))}
            {!organizations.isLoading && !organizations.data?.length && <p className="empty">입점한 판매자가 없습니다.</p>}
          </div>
        </>
      )}

      {tab === "traffic" && <PlatformTrafficPanel token={auth.access_token} />}
      {tab === "share" && <MarketSharePanel token={auth.access_token} />}
      {tab === "coupons" && <CouponAdminPanel token={auth.access_token} onError={onError} />}
    </main>
  );
}

function CouponAdminPanel({ token, onError }: { token: string; onError: (message: string) => void }) {
  const queryClient = useQueryClient();
  const coupons = useQuery({ queryKey: ["admin-coupons"], queryFn: () => getAdminCoupons(token) });
  const emptyForm = {
    code: "",
    discount_type: "PERCENT" as "PERCENT" | "FIXED",
    discount_value: "",
    max_discount_amount: "",
    min_purchase_amount: "0",
    expires_at: "",
  };
  const [form, setForm] = useState(emptyForm);
  const [showForm, setShowForm] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["admin-coupons"] });
    queryClient.invalidateQueries({ queryKey: ["active-coupons"] });
  };

  const create = useMutation({
    mutationFn: () =>
      createCoupon(token, {
        code: form.code,
        discount_type: form.discount_type,
        discount_value: Number(form.discount_value),
        max_discount_amount: form.max_discount_amount ? Number(form.max_discount_amount) : undefined,
        min_purchase_amount: Number(form.min_purchase_amount) || 0,
        expires_at: form.expires_at ? new Date(`${form.expires_at}T23:59:59`).toISOString() : undefined,
      } satisfies CouponInput),
    onSuccess: () => {
      invalidate();
      setShowForm(false);
      setForm(emptyForm);
    },
    onError: (error: Error) => onError(error.message),
  });

  const toggle = useMutation({
    mutationFn: (coupon: Coupon) => updateCouponActive(token, coupon.id, !coupon.is_active),
    onSuccess: invalidate,
    onError: (error: Error) => onError(error.message),
  });

  return (
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>쿠폰을 만들면 소비자가 사이트 접속 시 자동으로 안내 팝업을 보게 됩니다.</p>
        <button className="primary dark" onClick={() => setShowForm((value) => !value)}>{showForm ? "취소" : "쿠폰 만들기"}</button>
      </div>
      {showForm && (
        <form className="form-grid seller-product-form" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <label>쿠폰 코드<input required value={form.code} onChange={(e) => setForm((c) => ({ ...c, code: e.target.value.toUpperCase() }))} placeholder="SUMMER20" /></label>
          <label>할인 방식
            <select value={form.discount_type} onChange={(e) => setForm((c) => ({ ...c, discount_type: e.target.value as "PERCENT" | "FIXED" }))}>
              <option value="PERCENT">퍼센트 할인(%)</option>
              <option value="FIXED">정액 할인(원)</option>
            </select>
          </label>
          <label>{form.discount_type === "PERCENT" ? "할인율(%)" : "할인 금액(원)"}<input required type="number" min={1} value={form.discount_value} onChange={(e) => setForm((c) => ({ ...c, discount_value: e.target.value }))} /></label>
          {form.discount_type === "PERCENT" && (
            <label>최대 할인 금액(원, 선택)<input type="number" min={1} value={form.max_discount_amount} onChange={(e) => setForm((c) => ({ ...c, max_discount_amount: e.target.value }))} /></label>
          )}
          <label>최소 구매 금액(원)<input required type="number" min={0} value={form.min_purchase_amount} onChange={(e) => setForm((c) => ({ ...c, min_purchase_amount: e.target.value }))} /></label>
          <label>사용 기한(선택, 비우면 무기한)<input type="date" value={form.expires_at} onChange={(e) => setForm((c) => ({ ...c, expires_at: e.target.value }))} /></label>
          <div className="form-actions wide">
            <button type="button" className="ghost" onClick={() => setShowForm(false)}>취소</button>
            <button className="primary dark" disabled={create.isPending}>{create.isPending ? "생성 중…" : "쿠폰 생성"}</button>
          </div>
        </form>
      )}
      <div className="admin-org-list">
        {coupons.isLoading && <p className="empty">불러오는 중…</p>}
        {coupons.data?.map((coupon) => (
          <article className="admin-org-row" key={coupon.id}>
            <div>
              <span className={`state ${coupon.is_active ? "active" : "disconnected"}`}>{coupon.is_active ? "사용 중" : "중지됨"}</span>
              <h3>{coupon.code}</h3>
              <small>
                {coupon.discount_type === "PERCENT" ? `${coupon.discount_value}% 할인` : `${won.format(coupon.discount_value)} 할인`}
                {coupon.max_discount_amount ? ` (최대 ${won.format(coupon.max_discount_amount)})` : ""}
                {" · "}{won.format(coupon.min_purchase_amount)} 이상 구매 시
                {" · "}{coupon.expires_at ? `${coupon.expires_at.slice(0, 10)}까지` : "기한 없음"}
              </small>
            </div>
            <button
              className={coupon.is_active ? "danger-button" : "primary dark"}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(coupon)}
            >
              {coupon.is_active ? "중지" : "재개"}
            </button>
          </article>
        ))}
        {!coupons.isLoading && !coupons.data?.length && <p className="empty">생성된 쿠폰이 없습니다.</p>}
      </div>
    </div>
  );
}

function PlatformTrafficPanel({ token }: { token: string }) {
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
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>사이트 전체(모든 판매자 상품 포함) 오늘 조회수입니다. 판매자 콘솔에는 노출되지 않는 관리자 전용 데이터입니다.</p>
        <button className="primary dark" disabled={discordMutation.isPending || query.isLoading} onClick={() => discordMutation.mutate()}>
          {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
        </button>
      </div>
      {query.isLoading && <p className="empty">불러오는 중…</p>}
      {snapshot && (
        <>
          <div className="console-stats">
            <article><span>전체 조회수</span><strong>{snapshot.total_views}</strong></article>
            <article><span>날짜</span><strong>{snapshot.date}</strong></article>
          </div>
          <div className="console-grid-two">
            <div className="console-card">
              <h4>상점별 조회수 순위</h4>
              {snapshot.store_ranking.slice(0, 8).map((row) => <p key={row.org_name}>{row.org_name}: <b>{row.views}회</b></p>)}
            </div>
            <div className="console-card">
              <h4>가장 적게 조회된 상품</h4>
              {snapshot.least_viewed_products.slice(0, 5).map((row) => <p key={row.product_id}>{row.product_name} ({row.org_name}): <b>{row.views}회</b></p>)}
            </div>
          </div>
          <div className="console-card">
            <h4>AI 리포트</h4>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="console-footnote">{report!.model} · {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"} · {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}</footer>
          </div>
        </>
      )}
    </div>
  );
}

function MarketSharePanel({ token }: { token: string }) {
  const query = useQuery({
    queryKey: ["seller-market-share"],
    queryFn: () => getSellerMarketShare(token, false),
  });
  const discordMutation = useMutation({
    mutationFn: () => getSellerMarketShare(token, true),
  });
  const report: SellerMarketShareReport | undefined = discordMutation.data ?? query.data;
  const snapshot = report?.snapshot;
  const planLabel: Record<string, string> = { FREE: "무료 입점", BASIC: "Basic", PRO: "Pro", BUSINESS: "Business" };

  return (
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>판매자 매출액이 아니라, 수수료+플랜 요금으로 이 사이트가 실제로 버는 돈을 판매자별로 비교합니다.</p>
        <button className="primary dark" disabled={discordMutation.isPending || query.isLoading} onClick={() => discordMutation.mutate()}>
          {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
        </button>
      </div>
      {query.isLoading && <p className="empty">불러오는 중…</p>}
      {snapshot && (
        <>
          <div className="console-stats">
            <article><span>플랫폼 전체 매출</span><strong>{won.format(snapshot.total_platform_revenue)}</strong></article>
            <article><span>플랫폼 기본 상품 비중</span><strong>{snapshot.platform_default_share_pct ?? "—"}%</strong></article>
            <article><span>이번 달</span><strong>{snapshot.period}</strong></article>
          </div>
          <div className="seller-product-list">
            {snapshot.sellers.map((seller) => (
              <article className="market-share-row" key={seller.org_id}>
                <div>
                  <h3>{seller.org_name} · {planLabel[seller.plan] ?? seller.plan}</h3>
                  <small>판매액 {won.format(seller.gross_revenue)} · 수수료+플랜 {won.format(seller.platform_contribution)}</small>
                </div>
                <strong>{seller.share_pct ?? "—"}%</strong>
              </article>
            ))}
          </div>
          <div className="console-card">
            <h4>AI 리포트</h4>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="console-footnote">{report!.model} · {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"} · {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}</footer>
          </div>
        </>
      )}
    </div>
  );
}
