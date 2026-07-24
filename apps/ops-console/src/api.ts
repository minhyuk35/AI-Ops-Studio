import type {
  AuditLog,
  CommerceInsight,
  FailedJob,
  Inquiry,
  KnowledgeDocument,
  MonthlyReport,
  OpsIntegration,
  OpsWorkflow,
  ProductMetric,
  RevenueSummary,
} from "@ai-ops/shared-types";

const coreBaseUrl = import.meta.env.VITE_CORE_API_URL ?? "http://localhost:8000";
const commerceBaseUrl = import.meta.env.VITE_COMMERCE_API_URL ?? "http://localhost:8001";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${coreBaseUrl}/api/v1${path}`, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `요청에 실패했습니다. (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function commerceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${commerceBaseUrl}${path}`, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `요청에 실패했습니다. (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const json = (method: "POST" | "PATCH", body?: unknown, token?: string): RequestInit => ({
  method,
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const authGet = (path: string, token: string) =>
  fetch(`${coreBaseUrl}/api/v1${path}`, { headers: { Authorization: `Bearer ${token}` } });

export type ConsoleRole = "SELLER" | "ADMIN";

export interface ConsoleOrganization {
  id: string;
  name: string;
  category: string;
  commission_rate: number;
  status: string;
}

export interface ConsoleProfile {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  role: "CONSUMER" | ConsoleRole;
  organization: ConsoleOrganization | null;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  customer: ConsoleProfile;
}

export const login = (email: string, password: string) =>
  commerceRequest<AuthSession>(
    "/auth/login",
    json("POST", { email, password }),
  );

export const getMyProfile = (token: string) =>
  commerceRequest<ConsoleProfile>("/customers/me", {
    headers: { Authorization: `Bearer ${token}` },
  });

export const getInquiries = (orgId?: string, token?: string) => {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return orgId && token
    ? authGet(`/inquiries${query}`, token).then((r) => r.json() as Promise<Inquiry[]>)
    : request<Inquiry[]>(`/inquiries${query}`);
};
export const getInquiry = (id: string) => request<Inquiry>(`/inquiries/${id}`);
export const updateInquiry = (
  id: string,
  status: "ESCALATED" | "RESOLVED",
  note?: string,
) => request<Inquiry>(`/inquiries/${id}`, json("PATCH", { status, note }));

export const getWorkflows = () => request<OpsWorkflow[]>("/ops/workflows");
export const updateWorkflow = (id: string, status: "ACTIVE" | "PAUSED") =>
  request<OpsWorkflow>(`/ops/workflows/${id}`, json("PATCH", { status }));

export const getDocuments = () =>
  request<KnowledgeDocument[]>("/ops/knowledge-documents");
export const createDocument = (input: {
  title: string;
  category: string;
  content: string;
  source: string;
  status: "DRAFT" | "PUBLISHED";
}) => request<KnowledgeDocument>("/ops/knowledge-documents", json("POST", input));
export const updateDocument = (
  id: string,
  status: "DRAFT" | "PUBLISHED" | "ARCHIVED",
) => request<KnowledgeDocument>(
  `/ops/knowledge-documents/${id}`,
  json("PATCH", { status }),
);

export const getIntegrations = () =>
  request<OpsIntegration[]>("/ops/integrations");
export const checkIntegration = (id: string) =>
  request<OpsIntegration>(`/ops/integrations/${id}/check`, json("POST"));

export const getFailedJobs = () => request<FailedJob[]>("/ops/failed-jobs");
export const retryFailedJob = (id: string) =>
  request<FailedJob>(`/ops/failed-jobs/${id}/retry`, json("POST"));

export const getAuditLogs = () => request<AuditLog[]>("/ops/audit-logs");

export const getRevenueSummary = (period: string) =>
  request<RevenueSummary>(`/revenue/summary?period=${period}`);
export const getRevenueProducts = (period: string) =>
  request<ProductMetric[]>(`/revenue/products?period=${period}`);

export const getCommerceInsight = (period: string) =>
  request<CommerceInsight>(`/ai/commerce-insight?period=${period}`);
export const generateMonthlyReport = (period: string, sendDiscord: boolean) =>
  request<MonthlyReport>(
    "/ai/monthly-report",
    json("POST", { period, send_discord: sendDiscord }),
  );

export interface SellerDailyProduct {
  product_id: string;
  product_name: string;
  stock: number;
  views: number;
  units_sold: number;
  revenue: number;
  refund_units: number;
  refund_amount: number;
}

export interface SellerDailySnapshot {
  date: string;
  org_id: string;
  org_name: string;
  revenue: {
    gross_revenue: number;
    refund_amount: number;
    net_revenue: number;
    order_count: number;
  };
  products: SellerDailyProduct[];
  highlights: {
    most_viewed: SellerDailyProduct | null;
    least_viewed: SellerDailyProduct | null;
    most_purchased: SellerDailyProduct | null;
    most_refunded: SellerDailyProduct | null;
    out_of_stock: SellerDailyProduct[];
    low_stock: SellerDailyProduct[];
  };
}

export interface SellerDailyReport {
  date: string;
  org_id: string;
  org_name: string;
  report: string;
  snapshot: SellerDailySnapshot;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
  discord_sent: boolean;
}

export const getSellerDailyReport = (
  token: string,
  orgId: string,
  sendDiscord: boolean,
  date?: string,
) =>
  request<SellerDailyReport>(
    "/ai/seller-daily-report",
    json("POST", { org_id: orgId, date, send_discord: sendDiscord }, token),
  );

export interface PlatformTrafficProduct {
  product_id: string;
  product_name: string;
  org_name: string;
  views: number;
}

export interface PlatformTrafficSnapshot {
  date: string;
  total_views: number;
  top_products: PlatformTrafficProduct[];
  least_viewed_products: PlatformTrafficProduct[];
  store_ranking: { org_name: string; views: number }[];
}

export interface PlatformTrafficReport {
  date: string;
  report: string;
  snapshot: PlatformTrafficSnapshot;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
  discord_sent: boolean;
}

export const getPlatformDailyTraffic = (token: string, sendDiscord: boolean, date?: string) =>
  request<PlatformTrafficReport>(
    "/ai/platform-daily-traffic",
    json("POST", { date, send_discord: sendDiscord }, token),
  );

export interface SellerMarketShareRow {
  org_id: string;
  org_name: string;
  plan: "FREE" | "BASIC" | "PRO" | "BUSINESS";
  gross_revenue: number;
  refund_amount: number;
  net_revenue: number;
  commission_revenue: number;
  plan_fee: number;
  platform_contribution: number;
  share_pct: number | null;
  previous_share_pct: number | null;
}

export interface SellerMarketShareSnapshot {
  period: string;
  previous_period: string;
  total_platform_revenue: number;
  platform_default_revenue: number;
  platform_default_share_pct: number | null;
  sellers: SellerMarketShareRow[];
}

export interface SellerMarketShareReport {
  period: string;
  report: string;
  snapshot: SellerMarketShareSnapshot;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
  discord_sent: boolean;
}

export const getSellerMarketShare = (token: string, sendDiscord: boolean, period?: string) =>
  request<SellerMarketShareReport>(
    "/ai/seller-market-share",
    json("POST", { period, send_discord: sendDiscord }, token),
  );
