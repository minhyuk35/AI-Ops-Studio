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
    organization_id: "everyday-market",
    request_id: crypto.randomUUID().replaceAll("-", ""),
    channel: "demo-store",
  }));
