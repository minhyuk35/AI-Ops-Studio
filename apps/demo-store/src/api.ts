import type {
  AIReply,
  Cart,
  Category,
  Inquiry,
  Order,
  Product,
  ProductDetail,
} from "@ai-ops/shared-types";

const commerceBaseUrl = import.meta.env.VITE_COMMERCE_API_URL ?? "http://localhost:8001";
const coreBaseUrl = import.meta.env.VITE_CORE_API_URL ?? "http://localhost:8000";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `요청에 실패했습니다. (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const json = (method: string, body?: unknown, token?: string): RequestInit => ({
  method,
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const authGet = (token: string): RequestInit => ({
  headers: { Authorization: `Bearer ${token}` },
});

export type MarketplaceRole = "CONSUMER" | "SELLER" | "ADMIN";

export interface Organization {
  id: string;
  name: string;
  category: string;
  commission_rate: number;
  status: string;
}

export interface AuthCustomer {
  id: string;
  email: string;
  name: string;
  phone: string;
  is_admin: boolean;
  role: MarketplaceRole;
  organization: Organization | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  customer: AuthCustomer;
}

export interface SignupInput {
  email: string;
  password: string;
  name: string;
  phone: string;
  as_seller?: boolean;
  shop_name?: string;
  shop_category?: string;
}

export const signup = (input: SignupInput) =>
  request<AuthResponse>(`${commerceBaseUrl}/auth/signup`, json("POST", input));

export const login = (email: string, password: string) =>
  request<AuthResponse>(`${commerceBaseUrl}/auth/login`, json("POST", { email, password }));

export const googleAuth = (
  idToken: string,
  extra?: { as_seller?: boolean; shop_name?: string; shop_category?: string },
) =>
  request<AuthResponse>(
    `${commerceBaseUrl}/auth/google`,
    json("POST", { id_token: idToken, ...extra }),
  );

export const getMe = (token: string) =>
  request<AuthCustomer>(`${commerceBaseUrl}/customers/me`, authGet(token));

export const activateSeller = (
  token: string,
  input: { shop_name: string; shop_category: string },
) => request<AuthCustomer>(`${commerceBaseUrl}/sellers/activate`, json("POST", input, token));

export const getCategories = () => request<Category[]>(`${commerceBaseUrl}/categories`);

export function getProducts(params: {
  q?: string;
  category?: string;
  sort?: string;
  inStock?: boolean;
} = {}) {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.category) query.set("category", params.category);
  if (params.sort) query.set("sort", params.sort);
  if (params.inStock) query.set("in_stock", "true");
  return request<Product[]>(`${commerceBaseUrl}/products?${query}`);
}

export const getProduct = (slug: string) =>
  request<ProductDetail>(`${commerceBaseUrl}/products/${slug}`);

export interface RecommendedProduct {
  id: string;
  slug: string;
  name: string;
  brand: string;
  image: string;
  price: number;
  compare_at_price: number | null;
  category_name: string;
  category_slug: string;
  in_stock: boolean;
  match_score: number | null;
}

export interface HomeRecommendations {
  tier: 1 | 2 | 3;
  basis_product_name: string | null;
  items: RecommendedProduct[];
}

export interface RecommendationSection {
  category_id: string;
  category_name: string;
  items: RecommendedProduct[];
}

export interface Recommendations {
  tier: 1 | 2 | 3;
  basis_product_name: string | null;
  sections: RecommendationSection[];
}

export const getHomeRecommendations = (cartId?: string, token?: string) => {
  const query = cartId ? `?cart_id=${encodeURIComponent(cartId)}` : "";
  return request<HomeRecommendations>(
    `${commerceBaseUrl}/recommendations/home${query}`,
    json("GET", undefined, token),
  );
};

export const getRecommendations = (cartId?: string, token?: string) => {
  const query = cartId ? `?cart_id=${encodeURIComponent(cartId)}` : "";
  return request<Recommendations>(
    `${commerceBaseUrl}/recommendations${query}`,
    json("GET", undefined, token),
  );
};

export const recordProductView = (productId: string, customerId?: string) =>
  fetch(`${commerceBaseUrl}/events/product-view`, json("POST", { product_id: productId, customer_id: customerId ?? null }));

export const getCart = (cartId: string, couponCode?: string) => {
  const query = couponCode ? `?coupon_code=${encodeURIComponent(couponCode)}` : "";
  return request<Cart>(`${commerceBaseUrl}/carts/${cartId}${query}`);
};

export const addCartItem = (cartId: string, variantId: string, quantity = 1) =>
  request<Cart>(`${commerceBaseUrl}/carts/${cartId}/items`, json("POST", {
    variant_id: variantId,
    quantity,
  }));

export const updateCartItem = (cartId: string, itemId: string, quantity: number) =>
  request<Cart>(`${commerceBaseUrl}/carts/${cartId}/items/${itemId}`, json("PATCH", { quantity }));

export const deleteCartItem = (cartId: string, itemId: string) =>
  request<Cart>(`${commerceBaseUrl}/carts/${cartId}/items/${itemId}`, json("DELETE"));

export interface CheckoutInput {
  cart_id: string;
  email: string;
  recipient: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2: string;
  delivery_memo: string;
  coupon_code?: string;
}

// customer_id is never sent by the client — the server derives it from the
// Authorization token (or leaves the order unattributed for a guest
// checkout). See services/mock-commerce-api/app/main.py's create_order.
export const createOrder = (input: CheckoutInput, token?: string) =>
  request<Order>(`${commerceBaseUrl}/checkout/orders`, json("POST", input, token));

export const confirmPayment = (orderId: string, amount: number, method: "CARD" | "EASY_PAY") =>
  request<{ order: Order }>(`${commerceBaseUrl}/payments/confirm`, json("POST", {
    order_id: orderId,
    amount,
    method,
  }));

export const getOrders = (token: string) =>
  request<Order[]>(`${commerceBaseUrl}/customers/me/orders`, authGet(token));
export const getOrder = (orderId: string) =>
  request<Order>(`${commerceBaseUrl}/customers/me/orders/${orderId}`);
export const cancelOrder = (orderId: string, reason: string) =>
  request<Order>(`${commerceBaseUrl}/orders/${orderId}/cancel`, json("POST", { reason }));
export const returnOrder = (orderId: string, reason: string) =>
  request<{ order: Order }>(`${commerceBaseUrl}/orders/${orderId}/returns`, json("POST", { reason }));

export const getInquiries = (customerId: string) =>
  request<Inquiry[]>(`${coreBaseUrl}/api/v1/inquiries?customer_id=${encodeURIComponent(customerId)}`);
export const getInquiry = (inquiryId: string) =>
  request<Inquiry>(`${coreBaseUrl}/api/v1/inquiries/${inquiryId}`);

export const askSupport = (input: {
  question: string;
  order?: Order | null;
  product?: Product | ProductDetail | null;
  inquiryId?: string | null;
  sessionId: string;
  customerId: string;
}) =>
  request<AIReply>(`${coreBaseUrl}/api/v1/ai/reply`, json("POST", {
    question: input.question,
    order_id: input.order?.id,
    product_id: input.product?.id,
    inquiry_id: input.inquiryId,
    order_context: input.order ?? (input.product ? {
      product_id: input.product.id,
      product_name: input.product.name,
      price: input.product.price,
      in_stock: input.product.in_stock,
      variants: "variants" in input.product
        ? input.product.variants.map((variant) => ({
            option: `${variant.color} / ${variant.size}`,
            stock: variant.stock,
          }))
        : undefined,
    } : {}),
    policy_context:
      "상품 준비 중에는 주문 취소가 가능합니다. 배송 완료 후 7일 이내 미사용 상품은 반품을 신청할 수 있으며 단순 변심 반품비는 3,000원입니다.",
    session_id: input.sessionId,
    user_id: input.customerId,
    organization_id: "codilab",
    request_id: crypto.randomUUID().replaceAll("-", ""),
    channel: "demo-store",
  }));

export interface SellerVariant {
  id: string;
  sku: string;
  color: string;
  size: string;
  price: number;
  stock: number;
}

export interface SellerProduct {
  id: string;
  slug: string;
  category_id: string;
  org_id: string;
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
  created_at: string;
  variants: SellerVariant[];
}

export interface SellerProductInput {
  name: string;
  category_id: string;
  description: string;
  material?: string;
  care?: string;
  image?: string;
  price: number;
  compare_at_price?: number;
  color: string;
  size: string;
  stock: number;
}

export const getMyOrders = (token: string) =>
  request<Order[]>(`${commerceBaseUrl}/sellers/me/orders`, authGet(token));

export const cancelMyOrder = (token: string, orderId: string) =>
  request<Order>(
    `${commerceBaseUrl}/orders/${orderId}/cancel`,
    json("POST", { reason: "판매자 취소 처리" }, token),
  );

export const completeMyOrderRefund = (token: string, orderId: string) =>
  request<Order>(
    `${commerceBaseUrl}/sellers/me/orders/${orderId}/complete-refund`,
    json("POST", {}, token),
  );

export const getMyProducts = (token: string) =>
  request<SellerProduct[]>(`${commerceBaseUrl}/sellers/me/products`, authGet(token));

export const createMyProduct = (token: string, input: SellerProductInput) =>
  request<SellerProduct>(`${commerceBaseUrl}/sellers/me/products`, json("POST", input, token));

export const updateMyVariant = (
  token: string,
  productId: string,
  variantId: string,
  input: { stock: number; price?: number },
) =>
  request<SellerProduct>(
    `${commerceBaseUrl}/sellers/me/products/${productId}/variants/${variantId}`,
    json("PATCH", input, token),
  );

export interface DiscordPlanChannel {
  channel_key: string;
  name: string;
  persona: string | null;
  topic: string;
}

export interface DiscordChannel {
  channel_key: string;
  channel_id: string;
  channel_name: string;
  webhook_url: string;
}

export interface DiscordStatus {
  linked: boolean;
  guild_id: string | null;
  linked_at: string | null;
  plan: string;
  plan_channels: DiscordPlanChannel[];
  channels: DiscordChannel[];
  link_code?: string;
}

export const getDiscordStatus = (token: string) =>
  request<DiscordStatus>(`${commerceBaseUrl}/sellers/me/discord`, authGet(token));

export const createDiscordLinkCode = (token: string) =>
  request<DiscordStatus>(
    `${commerceBaseUrl}/sellers/me/discord/link-code`,
    json("POST", undefined, token),
  );

export interface OrganizationSummary {
  id: string;
  owner_customer_id: string;
  name: string;
  category: string;
  commission_rate: number;
  status: "ACTIVE" | "SUSPENDED";
  created_at: string;
  owner: { id: string; email: string; name: string } | null;
  product_count: number;
}

export const getOrganizations = (token: string) =>
  request<OrganizationSummary[]>(`${commerceBaseUrl}/admin/organizations`, authGet(token));

export const updateOrganizationStatus = (
  token: string,
  orgId: string,
  status: "ACTIVE" | "SUSPENDED",
) =>
  request<OrganizationSummary>(
    `${commerceBaseUrl}/admin/organizations/${orgId}`,
    json("PATCH", { status }, token),
  );

export const getOrgInquiries = (token: string, orgId: string) =>
  request<Inquiry[]>(
    `${coreBaseUrl}/api/v1/inquiries?org_id=${encodeURIComponent(orgId)}`,
    authGet(token),
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
  revenue: { gross_revenue: number; refund_amount: number; net_revenue: number; order_count: number };
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

export const getSellerDailyReport = (token: string, orgId: string, sendDiscord: boolean) =>
  request<SellerDailyReport>(
    `${coreBaseUrl}/api/v1/ai/seller-daily-report`,
    json("POST", { org_id: orgId, send_discord: sendDiscord }, token),
  );

export interface ProductStyleTag {
  product_id: string;
  color_family: string;
  style_tags: string[];
  model: string;
  prompt_source: "langfuse" | "fallback";
  prompt_version: string | null;
}

// 상품 등록 직후 판매자 콘솔이 호출 — 응답을 기다려 화면을 막지 않고
// best-effort로 태깅한다(실패해도 상품 등록 자체는 이미 끝난 상태).
export const tagProductAttributes = (productId: string) =>
  request<ProductStyleTag>(
    `${coreBaseUrl}/api/v1/ai/tag-product-attributes`,
    json("POST", { product_id: productId }),
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

export const getPlatformDailyTraffic = (token: string, sendDiscord: boolean) =>
  request<PlatformTrafficReport>(
    `${coreBaseUrl}/api/v1/ai/platform-daily-traffic`,
    json("POST", { send_discord: sendDiscord }, token),
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

export const getSellerMarketShare = (token: string, sendDiscord: boolean) =>
  request<SellerMarketShareReport>(
    `${coreBaseUrl}/api/v1/ai/seller-market-share`,
    json("POST", { send_discord: sendDiscord }, token),
  );
