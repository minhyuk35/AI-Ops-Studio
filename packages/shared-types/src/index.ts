export type OrderStatus =
  | "PENDING_PAYMENT"
  | "PREPARING"
  | "SHIPPING"
  | "DELIVERED"
  | "CANCELLED"
  | "RETURN_REQUESTED"
  | "REFUNDED";

export interface Category {
  id: string;
  slug: string;
  name: string;
  sort_order: number;
  parent_id: string | null;
}

export interface Product {
  id: string;
  slug: string;
  category_id: string;
  category_name: string;
  category_slug: string;
  brand: string;
  name: string;
  description: string;
  material: string;
  care: string;
  image: string;
  price: number;
  compare_at_price: number | null;
  rating: number;
  review_count: number;
  in_stock: boolean;
  color_family: string | null;
  style_tags: string | null;
}

export interface ProductVariant {
  id: string;
  sku: string;
  color: string;
  size: string;
  price: number;
  stock: number;
}

export interface ProductDetail extends Product {
  variants: ProductVariant[];
  shipping: { fee: number; free_threshold: number; estimated_days: string };
  return_policy: { window_days: number; return_fee: number; exchange_fee: number };
}

export interface CartItem {
  id: string;
  quantity: number;
  variant_id: string;
  sku: string;
  color: string;
  size: string;
  price: number;
  stock: number;
  product_id: string;
  slug: string;
  brand: string;
  name: string;
  image: string;
  line_total: number;
  available: boolean;
}

export interface Cart {
  id: string;
  items: CartItem[];
  item_count: number;
  subtotal: number;
  discount: number;
  shipping_fee: number;
  total: number;
  coupon_code: string | null;
  coupon_message: string | null;
  valid: boolean;
  free_shipping_remaining: number;
}

export interface Shipment {
  id: string;
  order_id: string;
  carrier: string | null;
  tracking_number: string | null;
  status: string;
  eta?: string;
  delivered_at?: string;
  updated_at: string;
}

export interface OrderItem {
  id: string;
  product_id: string;
  variant_id: string;
  product_name: string;
  sku: string;
  option_text: string;
  unit_price: number;
  quantity: number;
  line_total: number;
}

export interface Claim {
  id: string;
  order_id: string;
  type: "CANCEL" | "RETURN";
  reason: string;
  status: string;
  refund_amount: number;
  return_fee: number;
  created_at: string;
}

export interface Order {
  id: string;
  customer_id: string | null;
  email: string;
  recipient: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2: string;
  delivery_memo: string;
  status: OrderStatus;
  subtotal: number;
  discount: number;
  shipping_fee: number;
  total: number;
  points_used: number;
  payment_status: string;
  ordered_at: string;
  updated_at: string;
  items: OrderItem[];
  shipment: Shipment | null;
  claims: Claim[];
}

export interface InquiryMessage {
  id: string;
  role: "user" | "assistant" | "agent";
  content: string;
  model: string | null;
  prompt_source: string | null;
  prompt_version: string | null;
  trace_id: string | null;
  created_at: string;
}

export interface Inquiry {
  id: string;
  customer_id: string | null;
  customer_name: string;
  order_id: string | null;
  product_id: string | null;
  subject: string;
  status: "RECEIVED" | "AI_PROCESSING" | "AUTO_RESOLVED" | "ESCALATED" | "RESOLVED";
  category: "DELIVERY" | "CANCEL" | "REFUND" | "OTHER";
  channel: string;
  session_id: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
  last_message?: string;
  messages?: InquiryMessage[];
}

export interface AIReply {
  answer: string;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
  requires_human: boolean;
  category: "DELIVERY" | "CANCEL" | "REFUND" | "OTHER";
  risk: "LOW" | "MEDIUM" | "HIGH";
  inquiry_id: string;
  conversation_id: string;
  trace_id: string | null;
}

export interface CommerceInsight {
  period: string;
  insight: string;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
}

export interface MonthlyReport {
  period: string;
  report: string;
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
  discord_sent: boolean;
}

export interface OpsWorkflow {
  id: string;
  name: string;
  description: string;
  trigger_type: string;
  status: "ACTIVE" | "PAUSED";
  version: number;
  steps: string[];
  success_count: number;
  failure_count: number;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  category: string;
  status: "DRAFT" | "PUBLISHED" | "ARCHIVED";
  content: string;
  source: string;
  chunk_count: number;
  updated_at: string;
}

export interface OpsIntegration {
  id: string;
  name: string;
  provider: string;
  kind: string;
  status: "CONNECTED" | "DISCONNECTED" | "ERROR";
  config_summary: string;
  last_checked_at: string | null;
  updated_at: string;
}

export interface FailedJob {
  id: string;
  workflow_id: string | null;
  inquiry_id: string | null;
  error_code: string;
  error_message: string;
  payload: Record<string, unknown>;
  retry_count: number;
  status: "PENDING" | "FAILED" | "RESOLVED";
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  detail: string;
  created_at: string;
}

export interface RevenuePeriodMetrics {
  period: string;
  gross_revenue: number;
  refund_amount: number;
  net_revenue: number;
  order_count: number;
  average_order_value: number;
}

export interface RevenueSummary extends RevenuePeriodMetrics {
  previous_period: RevenuePeriodMetrics;
  change: {
    gross_revenue_pct: number | null;
    net_revenue_pct: number | null;
    order_count_pct: number | null;
    average_order_value_pct: number | null;
  };
}

export interface ProductMetric {
  product_id: string;
  product_name: string;
  units_sold: number;
  revenue: number;
  refund_units: number;
  refund_amount: number;
  refund_rate: number | null;
}
