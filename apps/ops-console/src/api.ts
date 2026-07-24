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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${coreBaseUrl}/api/v1${path}`, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `요청에 실패했습니다. (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const json = (method: "POST" | "PATCH", body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const getInquiries = () => request<Inquiry[]>("/inquiries");
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
