import type { Cart, Inquiry, Order, Product, ProductDetail } from "@ai-ops/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  addCartItem,
  askSupport,
  cancelOrder,
  confirmPayment,
  createOrder,
  deleteCartItem,
  getCart,
  getCategories,
  getInquiries,
  getInquiry,
  getOrder,
  getOrders,
  getProduct,
  getProducts,
  returnOrder,
  updateCartItem,
} from "./api";

type View = "home" | "catalog" | "product" | "cart" | "checkout" | "orders" | "order" | "inquiries";
type ChatMessage = { role: "user" | "assistant"; content: string };

const won = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });

function persistentId(key: string, prefix: string) {
  const existing = localStorage.getItem(key);
  if (existing) return existing;
  const value = `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
  localStorage.setItem(key, value);
  return value;
}

const cartId = persistentId("everyday-cart-id", "cart");
const supportSessionId = persistentId("everyday-support-session", "session");

const statusLabel: Record<string, string> = {
  PENDING_PAYMENT: "결제 대기",
  PREPARING: "상품 준비 중",
  SHIPPING: "배송 중",
  DELIVERED: "배송 완료",
  CANCELLED: "주문 취소",
  RETURN_REQUESTED: "반품 접수",
};

export function App() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("home");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("recommended");
  const [inStock, setInStock] = useState(false);
  const [productSlug, setProductSlug] = useState<string | null>(null);
  const [variantId, setVariantId] = useState("");
  const [orderId, setOrderId] = useState<string | null>(null);
  const [couponInput, setCouponInput] = useState("");
  const [couponCode, setCouponCode] = useState<string | undefined>();
  const [notice, setNotice] = useState("");
  const [selectedInquiryId, setSelectedInquiryId] = useState<string | null>(null);

  const categories = useQuery({ queryKey: ["categories"], queryFn: getCategories });
  const products = useQuery({
    queryKey: ["products", search, category, sort, inStock],
    queryFn: () => getProducts({ q: search, category, sort, inStock }),
  });
  const product = useQuery({
    queryKey: ["product", productSlug],
    queryFn: () => getProduct(productSlug!),
    enabled: Boolean(productSlug),
  });
  const cart = useQuery({
    queryKey: ["cart", cartId, couponCode],
    queryFn: () => getCart(cartId, couponCode),
  });
  const orders = useQuery({ queryKey: ["orders"], queryFn: getOrders });
  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => getOrder(orderId!),
    enabled: Boolean(orderId),
  });
  const inquiries = useQuery({ queryKey: ["inquiries", "customer"], queryFn: getInquiries });
  const inquiry = useQuery({
    queryKey: ["inquiry", selectedInquiryId],
    queryFn: () => getInquiry(selectedInquiryId!),
    enabled: Boolean(selectedInquiryId),
  });

  const setCart = (next: Cart) => queryClient.setQueryData(["cart", cartId, couponCode], next);
  const addToCart = useMutation({
    mutationFn: (selected: string) => addCartItem(cartId, selected),
    onSuccess: (next) => {
      setCart(next);
      setNotice("장바구니에 담았습니다.");
    },
    onError: (error: Error) => setNotice(error.message),
  });
  const updateCart = useMutation({
    mutationFn: ({ itemId, quantity }: { itemId: string; quantity: number }) =>
      updateCartItem(cartId, itemId, quantity),
    onSuccess: setCart,
    onError: (error: Error) => setNotice(error.message),
  });
  const removeCart = useMutation({
    mutationFn: (itemId: string) => deleteCartItem(cartId, itemId),
    onSuccess: setCart,
  });

  const openProduct = (item: Product) => {
    setProductSlug(item.slug);
    setVariantId("");
    setView("product");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const openOrder = (id: string) => {
    setOrderId(id);
    setView("order");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const runSearch = (event: FormEvent) => {
    event.preventDefault();
    setSearch(searchInput.trim());
    setView("catalog");
  };

  return (
    <div className="store-shell">
      <header className="store-header">
        <button className="wordmark" onClick={() => setView("home")}>EVERYDAY MARKET</button>
        <nav aria-label="주요 메뉴">
          <button onClick={() => setView("catalog")}>SHOP</button>
          <button onClick={() => setView("orders")}>주문·배송</button>
          <button onClick={() => setView("inquiries")}>문의 내역</button>
        </nav>
        <form className="header-search" onSubmit={runSearch} role="search">
          <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="상품 검색" aria-label="상품 검색" />
          <button>검색</button>
        </form>
        <button className="cart-button" onClick={() => setView("cart")}>BAG <b>{cart.data?.item_count ?? 0}</b></button>
      </header>

      {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={() => setNotice("")}>닫기</button></div>}

      {view === "home" && <Home products={products.data ?? []} onShop={() => setView("catalog")} onProduct={openProduct} />}
      {view === "catalog" && (
        <Catalog
          products={products.data ?? []}
          categories={categories.data ?? []}
          selectedCategory={category}
          sort={sort}
          inStock={inStock}
          search={search}
          onCategory={setCategory}
          onSort={setSort}
          onInStock={setInStock}
          onProduct={openProduct}
        />
      )}
      {view === "product" && product.data && (
        <ProductPage
          product={product.data}
          variantId={variantId}
          onVariant={setVariantId}
          onAdd={() => {
            if (!variantId) return setNotice("옵션을 선택해주세요.");
            addToCart.mutate(variantId);
          }}
          onBuy={() => {
            if (!variantId) return setNotice("옵션을 선택해주세요.");
            addToCart.mutate(variantId, { onSuccess: () => setView("cart") });
          }}
        />
      )}
      {view === "cart" && (
        <CartPage
          cart={cart.data}
          couponInput={couponInput}
          onCouponInput={setCouponInput}
          onApplyCoupon={() => setCouponCode(couponInput.trim() || undefined)}
          onQuantity={(itemId, quantity) => updateCart.mutate({ itemId, quantity })}
          onRemove={(itemId) => removeCart.mutate(itemId)}
          onContinue={() => setView("catalog")}
          onCheckout={() => setView("checkout")}
        />
      )}
      {view === "checkout" && cart.data && (
        <CheckoutPage
          cart={cart.data}
          couponCode={couponCode}
          onBack={() => setView("cart")}
          onComplete={(completedOrder) => {
            setOrderId(completedOrder.id);
            queryClient.invalidateQueries({ queryKey: ["orders"] });
            queryClient.invalidateQueries({ queryKey: ["cart"] });
            setView("order");
          }}
          onError={setNotice}
        />
      )}
      {view === "orders" && <OrdersPage orders={orders.data ?? []} onOrder={openOrder} />}
      {view === "order" && order.data && (
        <OrderPage
          order={order.data}
          onCancel={async () => {
            try {
              await cancelOrder(order.data.id, "고객 요청");
              await queryClient.invalidateQueries({ queryKey: ["order", order.data.id] });
              await queryClient.invalidateQueries({ queryKey: ["orders"] });
            } catch (error) { setNotice((error as Error).message); }
          }}
          onReturn={async () => {
            try {
              await returnOrder(order.data.id, "단순 변심");
              await queryClient.invalidateQueries({ queryKey: ["order", order.data.id] });
              await queryClient.invalidateQueries({ queryKey: ["orders"] });
            } catch (error) { setNotice((error as Error).message); }
          }}
        />
      )}
      {view === "inquiries" && (
        <InquiryPage
          inquiries={inquiries.data ?? []}
          selected={inquiry.data}
          onSelect={setSelectedInquiryId}
        />
      )}

      <SupportChat order={order.data ?? null} product={product.data ?? null} onSaved={() => {
        queryClient.invalidateQueries({ queryKey: ["inquiries"] });
      }} />

      <footer>
        <strong>EVERYDAY MARKET</strong>
        <p>대표 홍길동 · 서울특별시 중구 세종대로 110 · 02-000-0000 · help@everyday.market</p>
        <p>사업자등록번호 000-00-00000 · 통신판매업 신고 정보는 데모 프로젝트용 예시입니다.</p>
        <div><a href="#terms">이용약관</a><a href="#privacy">개인정보처리방침</a><a href="#returns">배송·교환·반품 정책</a></div>
        <small>Product photography provided under the Unsplash License.</small>
      </footer>
    </div>
  );
}

function Home({ products, onShop, onProduct }: { products: Product[]; onShop: () => void; onProduct: (p: Product) => void }) {
  return <main>
    <section className="hero">
      <p className="eyebrow">NEW SEASON · 2026</p>
      <h1>매일의 옷을<br />조금 더 선명하게.</h1>
      <p>오래 입을 수 있는 소재와 절제된 실루엣을 고릅니다.</p>
      <button className="primary" onClick={onShop}>컬렉션 보기</button>
    </section>
    <section className="store-section"><SectionTitle eyebrow="EDITOR'S PICK" title="이번 주 에디터 추천" />
      <ProductGrid products={products.slice(0, 3)} onProduct={onProduct} />
    </section>
    <section className="benefits"><article><b>10만원 이상 무료배송</b><span>평균 2~3영업일 내 도착</span></article><article><b>7일 이내 반품 신청</b><span>주문 상세에서 간편 접수</span></article><article><b>AI 고객지원</b><span>주문 문맥을 연결한 빠른 답변</span></article></section>
  </main>;
}

function Catalog(props: { products: Product[]; categories: { slug: string; name: string }[]; selectedCategory: string; sort: string; inStock: boolean; search: string; onCategory: (v: string) => void; onSort: (v: string) => void; onInStock: (v: boolean) => void; onProduct: (p: Product) => void }) {
  return <main className="store-section catalog-page"><SectionTitle eyebrow="SHOP" title={props.search ? `“${props.search}” 검색 결과` : "전체 상품"} />
    <div className="catalog-tools"><div className="category-tabs"><button className={!props.selectedCategory ? "active" : ""} onClick={() => props.onCategory("")}>전체</button>{props.categories.map((item) => <button className={props.selectedCategory === item.slug ? "active" : ""} key={item.slug} onClick={() => props.onCategory(item.slug)}>{item.name}</button>)}</div>
      <div className="filters"><label><input type="checkbox" checked={props.inStock} onChange={(event) => props.onInStock(event.target.checked)} /> 재고 있음</label><select value={props.sort} onChange={(event) => props.onSort(event.target.value)} aria-label="상품 정렬"><option value="recommended">추천순</option><option value="newest">신상품순</option><option value="price_asc">낮은 가격순</option><option value="price_desc">높은 가격순</option><option value="reviews">리뷰순</option></select></div></div>
    {props.products.length ? <ProductGrid products={props.products} onProduct={props.onProduct} /> : <div className="empty"><h2>조건에 맞는 상품이 없습니다.</h2><button onClick={() => props.onCategory("")}>필터 초기화</button></div>}
  </main>;
}

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) { return <div className="section-title"><p>{eyebrow}</p><h2>{title}</h2></div>; }

function ProductGrid({ products, onProduct }: { products: Product[]; onProduct: (p: Product) => void }) {
  return <div className="product-grid">{products.map((item) => <button className="product-card" key={item.id} onClick={() => onProduct(item)}><div className="product-image"><img src={item.image} alt={item.name} loading="lazy" />{!item.in_stock && <span>품절</span>}</div><small>{item.brand}</small><h3>{item.name}</h3><div className="price">{item.compare_at_price && <del>{won.format(item.compare_at_price)}</del>}<b>{won.format(item.price)}</b></div><p>★ {item.rating.toFixed(1)} <span>({item.review_count})</span></p></button>)}</div>;
}

function ProductPage({ product, variantId, onVariant, onAdd, onBuy }: { product: ProductDetail; variantId: string; onVariant: (id: string) => void; onAdd: () => void; onBuy: () => void }) {
  return <main className="product-page"><div className="product-gallery"><img src={product.image} alt={product.name} /></div><div className="product-info"><small>{product.brand} · {product.category_name}</small><h1>{product.name}</h1><p className="rating">★ {product.rating} · 리뷰 {product.review_count}개</p><div className="product-price">{product.compare_at_price && <del>{won.format(product.compare_at_price)}</del>}<strong>{won.format(product.price)}</strong></div><p className="description">{product.description}</p><fieldset><legend>옵션 선택</legend>{product.variants.map((variant) => <button type="button" disabled={!variant.stock} className={variantId === variant.id ? "selected" : ""} key={variant.id} onClick={() => onVariant(variant.id)}>{variant.color} / {variant.size}{!variant.stock && " · 품절"}</button>)}</fieldset><div className="purchase-actions"><button onClick={onAdd}>장바구니</button><button className="dark" onClick={onBuy}>바로 구매</button></div><dl className="policy-list"><div><dt>배송</dt><dd>{product.shipping.estimated_days} · {won.format(product.shipping.fee)} · {won.format(product.shipping.free_threshold)} 이상 무료</dd></div><div><dt>반품</dt><dd>수령 후 {product.return_policy.window_days}일 이내 · 단순 변심 {won.format(product.return_policy.return_fee)}</dd></div><div><dt>소재</dt><dd>{product.material}</dd></div><div><dt>관리</dt><dd>{product.care}</dd></div></dl></div></main>;
}

function CartPage({ cart, couponInput, onCouponInput, onApplyCoupon, onQuantity, onRemove, onContinue, onCheckout }: { cart?: Cart; couponInput: string; onCouponInput: (v: string) => void; onApplyCoupon: () => void; onQuantity: (id: string, q: number) => void; onRemove: (id: string) => void; onContinue: () => void; onCheckout: () => void }) {
  if (!cart?.items.length) return <main className="store-section empty"><h1>장바구니가 비어 있습니다.</h1><button className="primary dark" onClick={onContinue}>상품 보러 가기</button></main>;
  return <main className="store-section cart-page"><SectionTitle eyebrow="SHOPPING BAG" title={`장바구니 ${cart.item_count}개`} /><div className="cart-layout"><div>{cart.items.map((item) => <article className="cart-item" key={item.id}><img src={item.image} alt="" /><div><small>{item.brand}</small><h3>{item.name}</h3><p>{item.color} / {item.size}</p><div className="quantity"><button disabled={item.quantity <= 1} onClick={() => onQuantity(item.id, item.quantity - 1)}>−</button><span>{item.quantity}</span><button disabled={item.quantity >= item.stock} onClick={() => onQuantity(item.id, item.quantity + 1)}>+</button></div></div><div><b>{won.format(item.line_total)}</b><button className="link" onClick={() => onRemove(item.id)}>삭제</button></div></article>)}</div><aside className="summary"><h2>주문 요약</h2><div className="coupon"><input value={couponInput} onChange={(e) => onCouponInput(e.target.value)} placeholder="WELCOME10" /><button onClick={onApplyCoupon}>적용</button></div>{cart.coupon_message && <small>{cart.coupon_message}</small>}<p><span>상품금액</span><b>{won.format(cart.subtotal)}</b></p><p><span>할인</span><b>−{won.format(cart.discount)}</b></p><p><span>배송비</span><b>{won.format(cart.shipping_fee)}</b></p><p className="total"><span>결제 예정금액</span><strong>{won.format(cart.total)}</strong></p><button className="primary dark block" disabled={!cart.valid} onClick={onCheckout}>주문하기</button></aside></div></main>;
}

function CheckoutPage({ cart, couponCode, onBack, onComplete, onError }: { cart: Cart; couponCode?: string; onBack: () => void; onComplete: (order: Order) => void; onError: (message: string) => void }) {
  const [form, setForm] = useState({ email: "demo@example.com", recipient: "김민지", phone: "010-0000-0000", postal_code: "04524", address1: "서울특별시 중구 세종대로 110", address2: "101호", delivery_memo: "문 앞에 놓아주세요." });
  const [method, setMethod] = useState<"CARD" | "EASY_PAY">("CARD");
  const mutation = useMutation({ mutationFn: async () => { const pending = await createOrder({ ...form, cart_id: cart.id, coupon_code: couponCode, customer_id: "cus_demo" }); const paid = await confirmPayment(pending.id, pending.total, method); return paid.order; }, onSuccess: onComplete, onError: (error: Error) => onError(error.message) });
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <main className="store-section checkout-page"><SectionTitle eyebrow="CHECKOUT" title="주문서" /><form onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><section><h2>배송 정보</h2><div className="form-grid"><label>이메일<input type="email" required value={form.email} onChange={(e) => update("email", e.target.value)} /></label><label>받는 분<input required value={form.recipient} onChange={(e) => update("recipient", e.target.value)} /></label><label>연락처<input required value={form.phone} onChange={(e) => update("phone", e.target.value)} /></label><label>우편번호<input required value={form.postal_code} onChange={(e) => update("postal_code", e.target.value)} /></label><label className="wide">기본주소<input required value={form.address1} onChange={(e) => update("address1", e.target.value)} /></label><label className="wide">상세주소<input value={form.address2} onChange={(e) => update("address2", e.target.value)} /></label><label className="wide">배송 메모<input value={form.delivery_memo} onChange={(e) => update("delivery_memo", e.target.value)} /></label></div></section><section><h2>결제수단</h2><div className="payment-methods"><label><input type="radio" checked={method === "CARD"} onChange={() => setMethod("CARD")} /> 신용·체크카드</label><label><input type="radio" checked={method === "EASY_PAY"} onChange={() => setMethod("EASY_PAY")} /> 간편결제</label></div><p className="demo-note">포트폴리오 데모 결제로 실제 금액은 청구되지 않습니다.</p></section><section className="checkout-total"><p>최종 결제금액 <strong>{won.format(cart.total)}</strong></p><label><input type="checkbox" required /> 주문 내용과 배송·취소·반품 정책을 확인했으며 결제에 동의합니다.</label></section><div className="checkout-actions"><button type="button" onClick={onBack}>장바구니로</button><button className="primary dark" disabled={mutation.isPending}>{mutation.isPending ? "결제 처리 중…" : `${won.format(cart.total)} 결제하기`}</button></div></form></main>;
}

function OrdersPage({ orders, onOrder }: { orders: Order[]; onOrder: (id: string) => void }) { return <main className="store-section"><SectionTitle eyebrow="MY ACCOUNT" title="주문·배송" />{orders.length ? <div className="order-list">{orders.map((item) => <button key={item.id} onClick={() => onOrder(item.id)}><div><small>{new Date(item.ordered_at).toLocaleDateString("ko-KR")} · {item.id}</small><h3>{item.items[0]?.product_name}{item.items.length > 1 && ` 외 ${item.items.length - 1}건`}</h3><span>{statusLabel[item.status] ?? item.status}</span></div><strong>{won.format(item.total)}</strong></button>)}</div> : <div className="empty">주문 내역이 없습니다.</div>}</main>; }

function OrderPage({ order, onCancel, onReturn }: { order: Order; onCancel: () => void; onReturn: () => void }) { return <main className="store-section order-detail"><SectionTitle eyebrow={order.id} title={statusLabel[order.status] ?? order.status} /><div className="order-columns"><section><h2>주문 상품</h2>{order.items.map((item) => <article key={item.id}><div><b>{item.product_name}</b><span>{item.option_text} · {item.quantity}개</span></div><strong>{won.format(item.line_total)}</strong></article>)}</section><aside className="summary"><h2>결제 정보</h2><p><span>상품금액</span><b>{won.format(order.subtotal)}</b></p><p><span>할인</span><b>−{won.format(order.discount)}</b></p><p><span>배송비</span><b>{won.format(order.shipping_fee)}</b></p><p className="total"><span>결제금액</span><strong>{won.format(order.total)}</strong></p></aside></div><section className="shipment"><h2>배송 정보</h2><div className="timeline"><i className="done" /><i className={order.status !== "PENDING_PAYMENT" ? "done" : ""} /><i className={["SHIPPING", "DELIVERED"].includes(order.status) ? "done" : ""} /><i className={order.status === "DELIVERED" ? "done" : ""} /></div><div className="timeline-labels"><span>주문접수</span><span>상품준비</span><span>배송중</span><span>배송완료</span></div><p>{order.shipment?.carrier ?? "택배사 배정 전"} · {order.shipment?.tracking_number ?? "송장번호 준비 중"} · 도착 예정 {order.shipment?.eta ?? "확인 중"}</p></section><section className="address"><h2>받는 분</h2><p>{order.recipient} · {order.phone}</p><p>({order.postal_code}) {order.address1} {order.address2}</p></section><div className="claim-actions">{["PENDING_PAYMENT", "PREPARING"].includes(order.status) && <button onClick={onCancel}>주문 취소</button>}{order.status === "DELIVERED" && <button onClick={onReturn}>반품 신청</button>}</div>{order.claims.length > 0 && <section><h2>취소·반품 내역</h2>{order.claims.map((claim) => <p key={claim.id}>{claim.type} · {claim.status} · 환불 예정 {won.format(claim.refund_amount)}</p>)}</section>}</main>; }

function InquiryPage({ inquiries, selected, onSelect }: { inquiries: Inquiry[]; selected?: Inquiry; onSelect: (id: string) => void }) { return <main className="store-section"><SectionTitle eyebrow="SUPPORT" title="문의 내역" /><div className="inquiry-layout"><div className="inquiry-list">{inquiries.map((item) => <button key={item.id} onClick={() => onSelect(item.id)}><span>{item.category}</span><div><b>{item.subject}</b><small>{item.status} · 메시지 {item.message_count ?? 0}개</small></div></button>)}{!inquiries.length && <div className="empty">아직 문의 내역이 없습니다. 오른쪽 아래 AI 고객지원을 이용해보세요.</div>}</div>{selected && <section className="conversation"><h2>{selected.subject}</h2>{selected.messages?.map((message) => <div className={`bubble ${message.role}`} key={message.id}><b>{message.role === "user" ? "나" : "AI 고객지원"}</b><div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div><small>{new Date(message.created_at).toLocaleString("ko-KR")}</small></div>)}</section>}</div></main>; }

function SupportChat({ order, product, onSaved }: { order: Order | null; product: ProductDetail | null; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [inquiryId, setInquiryId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: "assistant", content: "안녕하세요. 상품, 배송, 취소·반품에 대해 물어보세요." }]);
  const context = useMemo(() => order ? `주문 ${order.id}` : product ? product.name : "일반 문의", [order, product]);
  const support = useMutation({ mutationFn: (text: string) => askSupport({ question: text, order, product, inquiryId, sessionId: supportSessionId }), onSuccess: (data) => { setInquiryId(data.inquiry_id); setMessages((current) => [...current, { role: "assistant", content: data.answer }]); onSaved(); }, onError: (error: Error) => setMessages((current) => [...current, { role: "assistant", content: error.message }]) });
  const submit = (event: FormEvent) => { event.preventDefault(); const text = question.trim(); if (!text) return; setMessages((current) => [...current, { role: "user", content: text }]); setQuestion(""); support.mutate(text); };
  if (!open) return <button className="chat-launcher" onClick={() => setOpen(true)} aria-label="AI 고객지원 열기">AI</button>;
  return <aside className="chat"><header><div><b>AI 고객지원</b><small>{context}</small></div><button onClick={() => setOpen(false)}>닫기</button></header><div className="messages">{messages.map((message, index) => <div className={`message ${message.role}`} key={index}><div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div></div>)}{support.isPending && <div className="message assistant">답변을 확인하고 있습니다…</div>}</div><form onSubmit={submit}><input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="문의 내용을 입력하세요" /><button disabled={support.isPending}>전송</button></form></aside>;
}
