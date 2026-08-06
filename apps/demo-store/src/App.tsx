import type { Cart, Category, Inquiry, Order, Product, ProductDetail } from "@ai-ops/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

gsap.registerPlugin(ScrollTrigger);

import {
  activateSeller,
  addCartItem,
  askSupport,
  AuthResponse,
  cancelMyOrder,
  cancelOrder,
  completeMyOrderRefund,
  confirmPayment,
  Coupon,
  CouponInput,
  createCoupon,
  createDiscordLinkCode,
  createMyProduct,
  createMyProductVariant,
  createOrder,
  deleteCartItem,
  deleteMyProductVariant,
  DiscordStatus,
  getActiveCoupons,
  getAdminCoupons,
  getCart,
  getCategories,
  getDiscordStatus,
  getInquiries,
  getInquiry,
  getMe,
  getMyOrders,
  getMyProducts,
  getOrder,
  getOrders,
  getMyReviews,
  getOrganizations,
  getOrgInquiries,
  getPlatformDailyTraffic,
  getProduct,
  getProductReviews,
  getProducts,
  getRecommendations,
  getSellerDailyReport,
  getSellerMarketShare,
  getHomeRecommendations,
  googleAuth,
  HomeRecommendations,
  login,
  OrganizationSummary,
  PlatformTrafficReport,
  Recommendations,
  RecommendedProduct,
  recordProductView,
  returnOrder,
  SellerDailyReport,
  SellerMarketShareReport,
  SellerProduct,
  SellerProductInput,
  SellerProductUpdateInput,
  SellerVariantInput,
  signup,
  SignupInput,
  submitReview,
  tagProductAttributes,
  updateCartItem,
  updateCouponActive,
  updateMyProduct,
  updateMyVariant,
  updateOrganizationStatus,
} from "./api";

type View =
  | "home"
  | "catalog"
  | "product"
  | "cart"
  | "checkout"
  | "orders"
  | "order"
  | "inquiries"
  | "login"
  | "signup"
  | "profile"
  | "seller"
  | "admin"
  | "recommendations";
type ChatMessage = { role: "user" | "assistant"; content: string };

const won = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });
const AUTH_STORAGE_KEY = "everyday-auth";

function persistentId(key: string, prefix: string) {
  const existing = localStorage.getItem(key);
  if (existing) return existing;
  const value = `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
  localStorage.setItem(key, value);
  return value;
}

function loadStoredAuth(): AuthResponse | null {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthResponse;
  } catch {
    return null;
  }
}

const cartId = persistentId("everyday-cart-id", "cart");
const supportSessionId = persistentId("everyday-support-session", "session");
// Anonymous browsers still get their own (unauthenticated) inquiry history
// instead of everyone sharing one identity.
const guestId = persistentId("everyday-guest-id", "guest");

const roleLabel: Record<string, string> = { CONSUMER: "소비자", SELLER: "판매자", ADMIN: "총관리자" };

// Thin concentric-ring line art used as quiet hero decoration — plain SVG,
// no runtime cost, no WebGL.
function HeroRings({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 300 300" fill="none" aria-hidden="true">
      <circle cx="150" cy="150" r="60" stroke="currentColor" strokeWidth="1" />
      <circle cx="150" cy="150" r="100" stroke="currentColor" strokeWidth="1" />
      <circle cx="150" cy="150" r="140" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

function Marquee({ text }: { text: string }) {
  const trackRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.to(trackRef.current, { xPercent: -50, duration: 16, ease: "none", repeat: -1 });
    });
    return () => ctx.revert();
  }, []);
  return (
    <div className="marquee">
      <div className="marquee-track" ref={trackRef}>
        <span>{text.repeat(4)}</span>
        <span aria-hidden="true">{text.repeat(4)}</span>
      </div>
    </div>
  );
}

function MagneticButton({
  className,
  onClick,
  children,
}: {
  className?: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const moveX = useRef<gsap.QuickToFunc | null>(null);
  const moveY = useRef<gsap.QuickToFunc | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    moveX.current = gsap.quickTo(ref.current, "x", { duration: 0.45, ease: "power3" });
    moveY.current = gsap.quickTo(ref.current, "y", { duration: 0.45, ease: "power3" });
  }, []);

  return (
    <button
      ref={ref}
      className={className}
      onClick={onClick}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        moveX.current?.((event.clientX - rect.left - rect.width / 2) * 0.4);
        moveY.current?.((event.clientY - rect.top - rect.height / 2) * 0.55);
      }}
      onMouseLeave={() => {
        moveX.current?.(0);
        moveY.current?.(0);
      }}
    >
      {children}
    </button>
  );
}

const statusLabel: Record<string, string> = {
  PENDING_PAYMENT: "결제 대기",
  PREPARING: "상품 준비 중",
  SHIPPING: "배송 중",
  DELIVERED: "배송 완료",
  CANCELLED: "주문 취소",
  RETURN_REQUESTED: "반품 접수",
  REFUNDED: "환불 완료",
};
const inquiryStatusLabel: Record<string, string> = {
  RECEIVED: "접수",
  AI_PROCESSING: "AI 처리 중",
  AUTO_RESOLVED: "AI 자동 해결",
  ESCALATED: "상담원 이관",
  RESOLVED: "해결",
};

const SEEN_COUPONS_KEY = "codilab-seen-coupons";

function CouponAnnouncement() {
  const [dismissedIds, setDismissedIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(SEEN_COUPONS_KEY) ?? "[]");
    } catch {
      return [];
    }
  });
  const coupons = useQuery({ queryKey: ["active-coupons"], queryFn: getActiveCoupons });
  const unseen = (coupons.data ?? []).filter((coupon) => !dismissedIds.includes(coupon.id));

  if (!unseen.length) return null;

  const dismiss = () => {
    const nextIds = [...dismissedIds, ...unseen.map((coupon) => coupon.id)];
    setDismissedIds(nextIds);
    localStorage.setItem(SEEN_COUPONS_KEY, JSON.stringify(nextIds));
  };

  return (
    <div className="coupon-popup-overlay" role="dialog" aria-modal="true">
      <div className="coupon-popup">
        <button className="coupon-popup-close" onClick={dismiss} aria-label="닫기">×</button>
        <p className="coupon-popup-eyebrow">🎁 신규 쿠폰 안내</p>
        {unseen.map((coupon) => (
          <div key={coupon.id} className="coupon-popup-item">
            <b>{coupon.code}</b>
            <span>
              {coupon.discount_type === "PERCENT" ? `${coupon.discount_value}% 할인` : `${won.format(coupon.discount_value)} 할인`}
              {coupon.min_purchase_amount > 0 && ` · ${won.format(coupon.min_purchase_amount)} 이상 구매 시`}
            </span>
          </div>
        ))}
        <button className="primary dark block" onClick={dismiss}>확인했어요</button>
      </div>
    </div>
  );
}

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
  const [auth, setAuth] = useState<AuthResponse | null>(loadStoredAuth);

  const identityId = auth?.customer.id ?? guestId;
  const persistAuth = (next: AuthResponse | null) => {
    setAuth(next);
    if (next) localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(next));
    else localStorage.removeItem(AUTH_STORAGE_KEY);
  };
  const logout = () => {
    persistAuth(null);
    setView("home");
    queryClient.invalidateQueries({ queryKey: ["orders"] });
    queryClient.invalidateQueries({ queryKey: ["inquiries"] });
  };

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
  const orders = useQuery({
    queryKey: ["orders", auth?.customer.id],
    queryFn: () => getOrders(auth!.access_token),
    enabled: Boolean(auth),
  });
  const order = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => getOrder(orderId!),
    enabled: Boolean(orderId),
  });
  const inquiries = useQuery({
    queryKey: ["inquiries", identityId],
    queryFn: () => getInquiries(identityId),
  });
  const inquiry = useQuery({
    queryKey: ["inquiry", selectedInquiryId],
    queryFn: () => getInquiry(selectedInquiryId!),
    enabled: Boolean(selectedInquiryId),
    // Sellers can reply from Discord (see the escalation embed's 답변 버튼) —
    // poll while a conversation is open so that reply shows up without the
    // customer having to manually refresh the page.
    refetchInterval: 5000,
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

  const openProduct = (item: { slug: string }) => {
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
      <CouponAnnouncement />
      <header className="store-header">
        <button className="wordmark" onClick={() => setView("home")}>코디랩</button>
        <nav aria-label="주요 메뉴">
          <button onClick={() => setView("catalog")}>SHOP</button>
          <button onClick={() => setView("recommendations")}>AI 추천</button>
          <button onClick={() => setView("orders")}>주문·배송</button>
          <button onClick={() => setView("inquiries")}>문의 내역</button>
        </nav>
        <form className="header-search" onSubmit={runSearch} role="search">
          <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="상품 검색" aria-label="상품 검색" />
          <button>검색</button>
        </form>
        <div className="header-actions">
          {auth ? (
            <button className="account-button" onClick={() => setView("profile")}>{auth.customer.name}</button>
          ) : (
            <button className="account-button" onClick={() => setView("login")}>로그인</button>
          )}
          <button className="cart-button" onClick={() => setView("cart")}>BAG <b>{cart.data?.item_count ?? 0}</b></button>
        </div>
      </header>

      <Marquee text="NEW SEASON — MINIMAL SILHOUETTE — MONOCHROME — CODILAB — " />

      {notice && <div className="notice" role="status"><span>{notice}</span><button onClick={() => setNotice("")}>닫기</button></div>}

      {view === "home" && (
        <Home
          products={products.data ?? []}
          onShop={() => setView("catalog")}
          onProduct={openProduct}
          onMore={() => setView("recommendations")}
          token={auth?.access_token}
        />
      )}
      {view === "recommendations" && (
        <AiRecommendationsPage onProduct={openProduct} token={auth?.access_token} />
      )}
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
          customerId={auth?.customer.id}
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
          token={auth?.access_token}
          defaultEmail={auth?.customer.email}
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
          token={auth?.access_token}
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
      {view === "login" && (
        <LoginPage
          onLoggedIn={(response) => { persistAuth(response); setView("profile"); }}
          onGoToSignup={() => setView("signup")}
          onError={setNotice}
        />
      )}
      {view === "signup" && (
        <SignupPage
          onSignedUp={(response) => { persistAuth(response); setView("profile"); }}
          onGoToLogin={() => setView("login")}
          onError={setNotice}
        />
      )}
      {view === "profile" && auth && (
        <ProfilePage
          auth={auth}
          onUpdated={persistAuth}
          onLogout={logout}
          onError={setNotice}
          onOpenSellerConsole={() => setView("seller")}
          onOpenAdminConsole={() => setView("admin")}
        />
      )}
      {view === "seller" && auth && (
        <SellerConsolePage
          auth={auth}
          categories={categories.data ?? []}
          onBack={() => setView("profile")}
          onError={setNotice}
        />
      )}
      {view === "admin" && auth && (
        <AdminConsolePage auth={auth} onBack={() => setView("profile")} onError={setNotice} />
      )}

      <SupportChat order={order.data ?? null} product={product.data ?? null} customerId={identityId} onSaved={() => {
        queryClient.invalidateQueries({ queryKey: ["inquiries"] });
        // AI support can auto-cancel an order (LOW-risk pre-shipment cancel)
        // without the customer ever clicking the page's own cancel button --
        // refetch so the order/shipping page reflects that immediately.
        if (order.data) queryClient.invalidateQueries({ queryKey: ["order", order.data.id] });
      }} />

      <footer>
        <strong>코디랩</strong>
        <p>대표 홍길동 · 서울특별시 중구 세종대로 110 · 02-000-0000 · help@codilab.market</p>
        <p>사업자등록번호 000-00-00000 · 통신판매업 신고 정보는 데모 프로젝트용 예시입니다.</p>
        <div><a href="#terms">이용약관</a><a href="#privacy">개인정보처리방침</a><a href="#returns">배송·교환·반품 정책</a></div>
        <small>Product photography provided under the Unsplash License.</small>
      </footer>
    </div>
  );
}

function Home({ products, onShop, onProduct, onMore, token }: { products: Product[]; onShop: () => void; onProduct: (p: { slug: string }) => void; onMore: () => void; token?: string }) {
  const heroRef = useRef<HTMLDivElement>(null);
  const editorialRef = useRef<HTMLDivElement>(null);
  const statementRef = useRef<HTMLDivElement>(null);
  const benefitsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.set(".hero-reveal", { opacity: 0, y: 34 });
      gsap.to(".hero-reveal", {
        opacity: 1,
        y: 0,
        duration: 1.1,
        ease: "power3.out",
        stagger: 0.12,
        delay: 0.15,
      });
    }, heroRef);
    return () => ctx.revert();
  }, []);

  useEffect(() => {
    if (!products.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".editorial-feature, .editorial-side .product-card",
        { opacity: 0, y: 34 },
        {
          opacity: 1,
          y: 0,
          duration: 0.8,
          ease: "power2.out",
          stagger: 0.12,
          scrollTrigger: { trigger: editorialRef.current, start: "top 85%" },
        },
      );
    }, editorialRef);
    return () => ctx.revert();
  }, [products]);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".statement-image",
        { scale: 1.18 },
        { scale: 1, duration: 1.6, ease: "power2.out", scrollTrigger: { trigger: statementRef.current, start: "top 80%" } },
      );
      gsap.fromTo(
        ".statement-text",
        { opacity: 0, y: 30 },
        { opacity: 1, y: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: statementRef.current, start: "top 70%" } },
      );
    }, statementRef);
    return () => ctx.revert();
  }, []);

  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".benefit-card",
        { opacity: 0, y: 24 },
        {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: "power2.out",
          stagger: 0.1,
          scrollTrigger: { trigger: benefitsRef.current, start: "top 85%" },
        },
      );
    }, benefitsRef);
    return () => ctx.revert();
  }, []);

  const [featured, ...rest] = products;

  return <main>
    <section className="hero" ref={heroRef}>
      <HeroRings className="hero-ring hero-ring-a" />
      <HeroRings className="hero-ring hero-ring-b" />
      <div className="hero-content">
        <p className="eyebrow hero-reveal">NEW SEASON · 2026</p>
        <h1 className="hero-heading hero-reveal">매일의 옷을<br />조금 더 선명하게.</h1>
        <p className="hero-reveal">오래 입을 수 있는 소재와 절제된 실루엣을 고릅니다.</p>
        <MagneticButton className="primary hero-reveal" onClick={onShop}>컬렉션 보기</MagneticButton>
      </div>
      <div className="hero-index hero-reveal" aria-hidden="true"><span>SHOP</span><span>·</span><span>SS 26</span></div>
    </section>

    <AiRecommendationsStrip onProduct={onProduct} onMore={onMore} token={token} />

    <section className="store-section editorial-section" ref={editorialRef}>
      <SectionTitle eyebrow="EDITOR'S PICK" title="이번 주 에디터 추천" />
      <div className="editorial-grid">
        {featured && (
          <button className="editorial-feature" onClick={() => onProduct(featured)}>
            <div className="product-image">
              <img src={featured.image} alt={featured.name} loading="lazy" />
              {!featured.in_stock && <span>품절</span>}
            </div>
            <div className="editorial-feature-meta">
              <small>{featured.brand}</small>
              <h3>{featured.name}</h3>
              <div className="price">{featured.compare_at_price && <del>{won.format(featured.compare_at_price)}</del>}<b>{won.format(featured.price)}</b></div>
            </div>
          </button>
        )}
        <div className="editorial-side">
          {rest.slice(0, 2).map((item) => (
            <button className="product-card" key={item.id} onClick={() => onProduct(item)}>
              <div className="product-image">
                <img src={item.image} alt={item.name} loading="lazy" />
                {!item.in_stock && <span>품절</span>}
              </div>
              <small>{item.brand}</small>
              <h3>{item.name}</h3>
              <div className="price">{item.compare_at_price && <del>{won.format(item.compare_at_price)}</del>}<b>{won.format(item.price)}</b></div>
            </button>
          ))}
        </div>
      </div>
    </section>

    <section className="statement" ref={statementRef}>
      <img
        className="statement-image"
        src="https://images.unsplash.com/photo-1598033129183-c4f50c736f10?auto=format&fit=crop&w=1800&q=85"
        alt=""
        aria-hidden="true"
      />
      <div className="statement-overlay" />
      <p className="statement-text">재질부터<br />다시 생각합니다.</p>
    </section>

    <section className="benefits" ref={benefitsRef}><article className="benefit-card"><b>10만원 이상 무료배송</b><span>평균 2~3영업일 내 도착</span></article><article className="benefit-card"><b>7일 이내 반품 신청</b><span>주문 상세에서 간편 접수</span></article><article className="benefit-card"><b>AI 고객지원</b><span>주문 문맥을 연결한 빠른 답변</span></article></section>
  </main>;
}

// 마우스 휠(세로 스크롤)을 가로 스크롤로 변환 — 트랙패드는 이미 자연스러운
// 가로 스크롤을 지원하므로, 세로 델타가 더 클 때만 가로로 바꿔치기한다.
function useWheelToHorizontalScroll(rowRef: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const el = rowRef.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      el.scrollLeft += event.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [rowRef]);
}

function AiRecChip({ item, onProduct }: { item: RecommendedProduct; onProduct: (p: { slug: string }) => void }) {
  return (
    <button className="ai-rec-chip" onClick={() => onProduct(item)}>
      <div className="ai-rec-chip-image">
        <img src={item.image} alt={item.name} loading="lazy" />
        {!item.in_stock && <span>품절</span>}
      </div>
      <small>{item.brand}</small>
      <h4>{item.name}</h4>
      <div className="price">{item.compare_at_price && <del>{won.format(item.compare_at_price)}</del>}<b>{won.format(item.price)}</b></div>
    </button>
  );
}

function AiRecRow({ items, onProduct }: { items: RecommendedProduct[]; onProduct: (p: { slug: string }) => void }) {
  const rowRef = useRef<HTMLDivElement>(null);
  useWheelToHorizontalScroll(rowRef);
  return (
    <div className="ai-rec-row" ref={rowRef}>
      {items.map((item) => <AiRecChip item={item} onProduct={onProduct} key={item.id} />)}
    </div>
  );
}

function AiRecommendationsStrip({ onProduct, onMore, token }: { onProduct: (p: { slug: string }) => void; onMore: () => void; token?: string }) {
  const sectionRef = useRef<HTMLDivElement>(null);
  const recs = useQuery({
    queryKey: ["home-recommendations", cartId, token],
    queryFn: () => getHomeRecommendations(cartId, token),
  });

  useEffect(() => {
    if (!recs.data?.items.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".ai-rec-chip",
        { opacity: 0, y: 24 },
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: "power2.out",
          stagger: 0.08,
          scrollTrigger: { trigger: sectionRef.current, start: "top 88%" },
        },
      );
    }, sectionRef);
    return () => ctx.revert();
  }, [recs.data]);

  if (!recs.data?.items.length) return null;
  const { tier, basis_product_name, items } = recs.data;
  const eyebrow = tier >= 2 ? "AI 추천 · 맞춤 코디" : "AI 추천 · 베스트 조합";
  const heading =
    tier >= 2 && basis_product_name ? (
      <>이번에 <b>{basis_product_name}</b>{tier === 3 ? " 구매하셨군요!" : " 보셨군요!"}</>
    ) : (
      "처음 오셨나봐요! 저희 쇼핑몰엔 이런게 있어요!"
    );

  return (
    <section className="store-section ai-recs-section" ref={sectionRef}>
      <div className="section-title ai-recs-title">
        <div>
          <p>{eyebrow}</p>
          <h2>{heading}</h2>
        </div>
        <button className="link" onClick={onMore}>더보기 →</button>
      </div>
      <AiRecRow items={items} onProduct={onProduct} />
    </section>
  );
}

function AiRecommendationsPage({ onProduct, token }: { onProduct: (p: { slug: string }) => void; token?: string }) {
  const pageRef = useRef<HTMLDivElement>(null);
  const recs = useQuery({
    queryKey: ["recommendations", cartId, token],
    queryFn: () => getRecommendations(cartId, token),
  });

  useEffect(() => {
    if (!recs.data?.sections.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".ai-rec-chip",
        { opacity: 0, y: 24 },
        { opacity: 1, y: 0, duration: 0.6, ease: "power2.out", stagger: 0.06 },
      );
    }, pageRef);
    return () => ctx.revert();
  }, [recs.data]);

  const basis = recs.data?.basis_product_name;
  const tier = recs.data?.tier ?? 1;

  return (
    <main className="store-section ai-recommendations-page" ref={pageRef}>
      <SectionTitle eyebrow="AI 추천" title="AI에게 추천받기" />
      <p className="ai-recs-basis">
        {tier >= 2 && basis
          ? <>최근 보신 <b>{basis}</b>과 잘 어울리는 코디예요</>
          : "지금 가장 많이 함께 구매된 베스트 조합이에요"}
      </p>
      {recs.isLoading && <p className="empty">추천을 불러오는 중…</p>}
      {!recs.isLoading && !recs.data?.sections.length && (
        <div className="empty"><h2>아직 추천할 상품이 부족해요.</h2></div>
      )}
      {recs.data?.sections.map((section) => (
        <div className="ai-rec-section-group" key={section.category_id}>
          <h3>{section.category_name}</h3>
          <AiRecRow items={section.items} onProduct={onProduct} />
        </div>
      ))}
    </main>
  );
}

function Catalog(props: { products: Product[]; categories: Category[]; selectedCategory: string; sort: string; inStock: boolean; search: string; onCategory: (v: string) => void; onSort: (v: string) => void; onInStock: (v: boolean) => void; onProduct: (p: Product) => void }) {
  // 2단 카테고리: 대분류(부모) 탭 + 선택한 대분류에 속한 소분류 탭.
  // selectedCategory는 대분류 slug(그 대분류 전체) 또는 소분류 slug(단일 소분류) 둘 다 될 수 있음.
  const parents = props.categories.filter((c) => !c.parent_id);
  const selected = props.categories.find((c) => c.slug === props.selectedCategory);
  const activeParentSlug = !props.selectedCategory
    ? ""
    : selected && !selected.parent_id
      ? selected.slug
      : (props.categories.find((c) => c.id === selected?.parent_id)?.slug ?? "");
  const activeParent = props.categories.find((c) => c.slug === activeParentSlug);
  const children = activeParent ? props.categories.filter((c) => c.parent_id === activeParent.id) : [];

  return <main className="store-section catalog-page"><SectionTitle eyebrow="SHOP" title={props.search ? `“${props.search}” 검색 결과` : "전체 상품"} />
    <div className="catalog-tools">
      <div>
        <div className="category-tabs"><button className={!activeParentSlug ? "active" : ""} onClick={() => props.onCategory("")}>전체</button>{parents.map((item) => <button className={activeParentSlug === item.slug ? "active" : ""} key={item.slug} onClick={() => props.onCategory(item.slug)}>{item.name}</button>)}</div>
        {children.length > 0 && (
          <div className="subcategory-tabs">
            <button className={props.selectedCategory === activeParentSlug ? "active" : ""} onClick={() => props.onCategory(activeParentSlug)}>전체</button>
            {children.map((item) => <button className={props.selectedCategory === item.slug ? "active" : ""} key={item.slug} onClick={() => props.onCategory(item.slug)}>{item.name}</button>)}
          </div>
        )}
      </div>
      <div className="filters"><label><input type="checkbox" checked={props.inStock} onChange={(event) => props.onInStock(event.target.checked)} /> 재고 있음</label><select value={props.sort} onChange={(event) => props.onSort(event.target.value)} aria-label="상품 정렬"><option value="recommended">추천순</option><option value="newest">신상품순</option><option value="price_asc">낮은 가격순</option><option value="price_desc">높은 가격순</option><option value="reviews">리뷰순</option></select></div></div>
    {props.products.length ? <ProductGrid products={props.products} onProduct={props.onProduct} /> : <div className="empty"><h2>조건에 맞는 상품이 없습니다.</h2><button onClick={() => props.onCategory("")}>필터 초기화</button></div>}
  </main>;
}

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ref.current,
        { opacity: 0, y: 18 },
        { opacity: 1, y: 0, duration: 0.7, ease: "power2.out", scrollTrigger: { trigger: ref.current, start: "top 90%" } },
      );
    }, ref);
    return () => ctx.revert();
  }, [eyebrow, title]);
  return <div className="section-title" ref={ref}><p>{eyebrow}</p><h2>{title}</h2></div>;
}

function ProductGrid({ products, onProduct }: { products: Product[]; onProduct: (p: Product) => void }) {
  const gridRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!products.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".product-card",
        { opacity: 0, y: 28 },
        {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: "power2.out",
          stagger: 0.08,
          scrollTrigger: { trigger: gridRef.current, start: "top 88%" },
        },
      );
    }, gridRef);
    return () => ctx.revert();
  }, [products]);
  return <div className="product-grid" ref={gridRef}>{products.map((item) => <button className="product-card" key={item.id} onClick={() => onProduct(item)}><div className="product-image"><img src={item.image} alt={item.name} loading="lazy" />{!item.in_stock && <span>품절</span>}</div><small>{item.brand}</small><h3>{item.name}</h3><div className="price">{item.compare_at_price && <del>{won.format(item.compare_at_price)}</del>}<b>{won.format(item.price)}</b></div><p>★ {item.rating.toFixed(1)} <span>({item.review_count})</span></p></button>)}</div>;
}

function ProductReviews({ productId }: { productId: string }) {
  const reviews = useQuery({
    queryKey: ["product-reviews", productId],
    queryFn: () => getProductReviews(productId),
  });
  if (!reviews.data?.length) return null;
  return (
    <section className="store-section product-reviews">
      <SectionTitle eyebrow="REVIEWS" title={`리뷰 ${reviews.data.length}개`} />
      <div className="review-list">
        {reviews.data.map((review) => (
          <article key={review.id} className="review-card">
            <div className="review-card-head">
              <span className="review-stars-static">{"★".repeat(review.rating)}{"☆".repeat(5 - review.rating)}</span>
              <b>{review.customer_name}</b>
              <small>{review.created_at.slice(0, 10)}</small>
            </div>
            <p>{review.content}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function ProductPage({ product, variantId, customerId, onVariant, onAdd, onBuy }: { product: ProductDetail; variantId: string; customerId?: string; onVariant: (id: string) => void; onAdd: () => void; onBuy: () => void }) {
  useEffect(() => {
    recordProductView(product.id, customerId).catch(() => {});
  }, [product.id, customerId]);
  return <>
    <main className="product-page"><div className="product-gallery"><img src={product.image} alt={product.name} /></div><div className="product-info"><small>{product.brand} · {product.category_name}</small><h1>{product.name}</h1><p className="rating">★ {product.rating} · 리뷰 {product.review_count}개</p><div className="product-price">{product.compare_at_price && <del>{won.format(product.compare_at_price)}</del>}<strong>{won.format(product.price)}</strong></div><p className="description">{product.description}</p><fieldset><legend>옵션 선택</legend>{product.variants.map((variant) => <button type="button" disabled={!variant.stock} className={variantId === variant.id ? "selected" : ""} key={variant.id} onClick={() => onVariant(variant.id)}>{variant.color} / {variant.size}{!variant.stock && " · 품절"}</button>)}</fieldset><div className="purchase-actions"><button onClick={onAdd}>장바구니</button><button className="dark" onClick={onBuy}>바로 구매</button></div><dl className="policy-list"><div><dt>배송</dt><dd>{product.shipping.estimated_days} · {won.format(product.shipping.fee)} · {won.format(product.shipping.free_threshold)} 이상 무료</dd></div><div><dt>반품</dt><dd>수령 후 {product.return_policy.window_days}일 이내 · 단순 변심 {won.format(product.return_policy.return_fee)}</dd></div><div><dt>소재</dt><dd>{product.material}</dd></div><div><dt>관리</dt><dd>{product.care}</dd></div></dl></div></main>
    <ProductReviews productId={product.id} />
  </>;
}

function CartPage({ cart, couponInput, onCouponInput, onApplyCoupon, onQuantity, onRemove, onContinue, onCheckout }: { cart?: Cart; couponInput: string; onCouponInput: (v: string) => void; onApplyCoupon: () => void; onQuantity: (id: string, q: number) => void; onRemove: (id: string) => void; onContinue: () => void; onCheckout: () => void }) {
  if (!cart?.items.length) return <main className="store-section empty"><h1>장바구니가 비어 있습니다.</h1><button className="primary dark" onClick={onContinue}>상품 보러 가기</button></main>;
  return <main className="store-section cart-page"><SectionTitle eyebrow="SHOPPING BAG" title={`장바구니 ${cart.item_count}개`} /><div className="cart-layout"><div>{cart.items.map((item) => <article className="cart-item" key={item.id}><img src={item.image} alt="" /><div><small>{item.brand}</small><h3>{item.name}</h3><p>{item.color} / {item.size}</p><div className="quantity"><button disabled={item.quantity <= 1} onClick={() => onQuantity(item.id, item.quantity - 1)}>−</button><span>{item.quantity}</span><button disabled={item.quantity >= item.stock} onClick={() => onQuantity(item.id, item.quantity + 1)}>+</button></div></div><div><b>{won.format(item.line_total)}</b><button className="link" onClick={() => onRemove(item.id)}>삭제</button></div></article>)}</div><aside className="summary"><h2>주문 요약</h2><div className="coupon"><input value={couponInput} onChange={(e) => onCouponInput(e.target.value)} placeholder="WELCOME10" /><button onClick={onApplyCoupon}>적용</button></div>{cart.coupon_message && <small>{cart.coupon_message}</small>}<p><span>상품금액</span><b>{won.format(cart.subtotal)}</b></p><p><span>할인</span><b>−{won.format(cart.discount)}</b></p><p><span>배송비</span><b>{won.format(cart.shipping_fee)}</b></p><p className="total"><span>결제 예정금액</span><strong>{won.format(cart.total)}</strong></p><button className="primary dark block" disabled={!cart.valid} onClick={onCheckout}>주문하기</button></aside></div></main>;
}

function CheckoutPage({ cart, couponCode, token, defaultEmail, onBack, onComplete, onError }: { cart: Cart; couponCode?: string; token?: string; defaultEmail?: string; onBack: () => void; onComplete: (order: Order) => void; onError: (message: string) => void }) {
  const [form, setForm] = useState({ email: defaultEmail ?? "demo@example.com", recipient: "김민지", phone: "010-0000-0000", postal_code: "04524", address1: "서울특별시 중구 세종대로 110", address2: "101호", delivery_memo: "문 앞에 놓아주세요." });
  const [method, setMethod] = useState<"CARD" | "EASY_PAY">("CARD");
  const mutation = useMutation({ mutationFn: async () => { const pending = await createOrder({ ...form, cart_id: cart.id, coupon_code: couponCode }, token); const paid = await confirmPayment(pending.id, pending.total, method); return paid.order; }, onSuccess: onComplete, onError: (error: Error) => onError(error.message) });
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <main className="store-section checkout-page"><SectionTitle eyebrow="CHECKOUT" title="주문서" /><form onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}><section><h2>배송 정보</h2><div className="form-grid"><label>이메일<input type="email" required value={form.email} onChange={(e) => update("email", e.target.value)} /></label><label>받는 분<input required value={form.recipient} onChange={(e) => update("recipient", e.target.value)} /></label><label>연락처<input required value={form.phone} onChange={(e) => update("phone", e.target.value)} /></label><label>우편번호<input required value={form.postal_code} onChange={(e) => update("postal_code", e.target.value)} /></label><label className="wide">기본주소<input required value={form.address1} onChange={(e) => update("address1", e.target.value)} /></label><label className="wide">상세주소<input value={form.address2} onChange={(e) => update("address2", e.target.value)} /></label><label className="wide">배송 메모<input value={form.delivery_memo} onChange={(e) => update("delivery_memo", e.target.value)} /></label></div></section><section><h2>결제수단</h2><div className="payment-methods"><label><input type="radio" checked={method === "CARD"} onChange={() => setMethod("CARD")} /> 신용·체크카드</label><label><input type="radio" checked={method === "EASY_PAY"} onChange={() => setMethod("EASY_PAY")} /> 간편결제</label></div><p className="demo-note">포트폴리오 데모 결제로 실제 금액은 청구되지 않습니다.</p></section><section className="checkout-total"><p>최종 결제금액 <strong>{won.format(cart.total)}</strong></p><label><input type="checkbox" required /> 주문 내용과 배송·취소·반품 정책을 확인했으며 결제에 동의합니다.</label></section><div className="checkout-actions"><button type="button" onClick={onBack}>장바구니로</button><button className="primary dark" disabled={mutation.isPending}>{mutation.isPending ? "결제 처리 중…" : `${won.format(cart.total)} 결제하기`}</button></div></form></main>;
}

function OrdersPage({ orders, onOrder }: { orders: Order[]; onOrder: (id: string) => void }) { return <main className="store-section"><SectionTitle eyebrow="MY ACCOUNT" title="주문·배송" />{orders.length ? <div className="order-list">{orders.map((item) => <button key={item.id} onClick={() => onOrder(item.id)}><div><small>{new Date(item.ordered_at).toLocaleDateString("ko-KR")} · {item.id}</small><h3>{item.items[0]?.product_name}{item.items.length > 1 && ` 외 ${item.items.length - 1}건`}</h3><span>{statusLabel[item.status] ?? item.status}</span></div><strong>{won.format(item.total)}</strong></button>)}</div> : <div className="empty">주문 내역이 없습니다.</div>}</main>; }

function ReviewForm({
  submitting,
  onSubmit,
}: {
  submitting: boolean;
  onSubmit: (input: { rating: number; content: string }) => void;
}) {
  const [rating, setRating] = useState(5);
  const [content, setContent] = useState("");
  return (
    <form
      className="review-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ rating, content });
      }}
    >
      <div className="review-stars" role="radiogroup" aria-label="별점">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            type="button"
            key={value}
            className={value <= rating ? "active" : ""}
            aria-label={`${value}점`}
            onClick={() => setRating(value)}
          >★</button>
        ))}
      </div>
      <textarea
        required
        minLength={5}
        maxLength={1000}
        rows={3}
        placeholder="상품은 어떠셨나요?"
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <button className="primary dark" disabled={submitting}>{submitting ? "등록 중…" : "리뷰 등록"}</button>
    </form>
  );
}

function OrderPage({
  order,
  token,
  onCancel,
  onReturn,
}: {
  order: Order;
  token?: string;
  onCancel: () => void;
  onReturn: () => void;
}) {
  const queryClient = useQueryClient();
  const [reviewingItemId, setReviewingItemId] = useState<string | null>(null);
  const canReview = order.status === "DELIVERED" && Boolean(token);
  const myReviews = useQuery({
    queryKey: ["my-reviews", token],
    queryFn: () => getMyReviews(token!),
    enabled: canReview,
  });
  const reviewedProductIds = new Set((myReviews.data ?? []).map((review) => review.product_id));
  const submitReviewMutation = useMutation({
    mutationFn: (input: { product_id: string; rating: number; content: string }) =>
      submitReview(token!, { order_id: order.id, ...input }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-reviews", token] });
      setReviewingItemId(null);
    },
  });

  return (
    <main className="store-section order-detail">
      <SectionTitle eyebrow={order.id} title={statusLabel[order.status] ?? order.status} />
      <div className="order-columns">
        <section>
          <h2>주문 상품</h2>
          {order.items.map((item) => (
            <article key={item.id} className="order-item-row">
              <div className="order-item-row-main">
                <div><b>{item.product_name}</b><span>{item.option_text} · {item.quantity}개</span></div>
                <strong>{won.format(item.line_total)}</strong>
              </div>
              {canReview && (
                reviewedProductIds.has(item.product_id) ? (
                  <small className="review-done">✓ 리뷰 작성 완료</small>
                ) : reviewingItemId === item.id ? (
                  <ReviewForm
                    submitting={submitReviewMutation.isPending}
                    onSubmit={(input) =>
                      submitReviewMutation.mutate({ product_id: item.product_id, ...input })
                    }
                  />
                ) : (
                  <button className="link" onClick={() => setReviewingItemId(item.id)}>리뷰 작성</button>
                )
              )}
            </article>
          ))}
        </section>
        <aside className="summary">
          <h2>결제 정보</h2>
          <p><span>상품금액</span><b>{won.format(order.subtotal)}</b></p>
          <p><span>할인</span><b>−{won.format(order.discount)}</b></p>
          <p><span>배송비</span><b>{won.format(order.shipping_fee)}</b></p>
          <p className="total"><span>결제금액</span><strong>{won.format(order.total)}</strong></p>
        </aside>
      </div>
      <section className="shipment">
        <h2>배송 정보</h2>
        <div className="timeline">
          <i className="done" />
          <i className={order.status !== "PENDING_PAYMENT" ? "done" : ""} />
          <i className={["SHIPPING", "DELIVERED"].includes(order.status) ? "done" : ""} />
          <i className={order.status === "DELIVERED" ? "done" : ""} />
        </div>
        <div className="timeline-labels"><span>주문접수</span><span>상품준비</span><span>배송중</span><span>배송완료</span></div>
        <p>{order.shipment?.carrier ?? "택배사 배정 전"} · {order.shipment?.tracking_number ?? "송장번호 준비 중"} · 도착 예정 {order.shipment?.eta ?? "확인 중"}</p>
      </section>
      <section className="address">
        <h2>받는 분</h2>
        <p>{order.recipient} · {order.phone}</p>
        <p>({order.postal_code}) {order.address1} {order.address2}</p>
      </section>
      <div className="claim-actions">
        {["PENDING_PAYMENT", "PREPARING"].includes(order.status) && <button onClick={onCancel}>주문 취소</button>}
        {order.status === "DELIVERED" && <button onClick={onReturn}>반품 신청</button>}
      </div>
      {order.claims.length > 0 && (
        <section>
          <h2>취소·반품 내역</h2>
          {order.claims.map((claim) => (
            <p key={claim.id}>{claim.type} · {claim.status} · 환불 예정 {won.format(claim.refund_amount)}<br /><small>이 내역은 3일 이내 삭제됩니다.</small></p>
          ))}
        </section>
      )}
    </main>
  );
}

function InquiryPage({ inquiries, selected, onSelect }: { inquiries: Inquiry[]; selected?: Inquiry; onSelect: (id: string) => void }) {
  const scrollRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [selected?.id, selected?.messages?.length]);
  return <main className="store-section"><SectionTitle eyebrow="SUPPORT" title="문의 내역" /><div className="inquiry-layout"><div className="inquiry-list">{inquiries.map((item) => <button key={item.id} onClick={() => onSelect(item.id)}><span>{item.category}</span><div><b>{item.subject}</b><small>{item.status} · 메시지 {item.message_count ?? 0}개</small></div></button>)}{!inquiries.length && <div className="empty">아직 문의 내역이 없습니다. 오른쪽 아래 AI 고객지원을 이용해보세요.</div>}</div>{selected && <section className="conversation" ref={scrollRef}><h2>{selected.subject}</h2>{selected.messages?.map((message) => <div className={`bubble ${message.role}`} key={message.id}><b>{message.role === "user" ? "나" : message.role === "assistant" ? "AI 고객지원" : "판매자"}</b><div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div><small>{new Date(message.created_at).toLocaleString("ko-KR")}</small></div>)}</section>}</div></main>;
}

function SupportChat({ order, product, customerId, onSaved }: { order: Order | null; product: ProductDetail | null; customerId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [inquiryId, setInquiryId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: "assistant", content: "안녕하세요. 상품, 배송, 취소·반품에 대해 물어보세요." }]);
  const context = useMemo(() => order ? `주문 ${order.id}` : product ? product.name : "일반 문의", [order, product]);
  const support = useMutation({ mutationFn: (text: string) => askSupport({ question: text, order, product, inquiryId, sessionId: supportSessionId, customerId }), onSuccess: (data) => { setInquiryId(data.inquiry_id); setMessages((current) => [...current, { role: "assistant", content: data.answer }]); onSaved(); }, onError: (error: Error) => setMessages((current) => [...current, { role: "assistant", content: error.message }]) });
  const submit = (event: FormEvent) => { event.preventDefault(); const text = question.trim(); if (!text) return; setMessages((current) => [...current, { role: "user", content: text }]); setQuestion(""); support.mutate(text); };
  if (!open) return <button className="chat-launcher" onClick={() => setOpen(true)} aria-label="AI 고객지원 열기">AI</button>;
  return <aside className="chat"><header><div><b>AI 고객지원</b><small>{context}</small></div><button onClick={() => setOpen(false)}>닫기</button></header><div className="messages">{messages.map((message, index) => <div className={`message ${message.role}`} key={index}><div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div></div>)}{support.isPending && <div className="message assistant">답변을 확인하고 있습니다…</div>}</div><form onSubmit={submit}><input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="문의 내용을 입력하세요" /><button disabled={support.isPending}>전송</button></form></aside>;
}

// Google Identity Services loads as a plain <script> tag (no npm package),
// so this augments the ambient Window type just enough to call it typed.
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: { theme?: string; size?: string; text?: string; width?: number },
          ) => void;
        };
      };
    };
  }
}

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";
const GOOGLE_SCRIPT_ID = "google-identity-services";

function GoogleSignInButton({
  asSeller,
  shopName,
  shopCategory,
  onSuccess,
  onError,
}: {
  asSeller?: boolean;
  shopName?: string;
  shopCategory?: string;
  onSuccess: (auth: AuthResponse) => void;
  onError: (message: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    const container = containerRef.current;
    if (!container) return;

    const render = () => {
      if (!window.google || !container) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => {
          googleAuth(
            response.credential,
            asSeller ? { as_seller: true, shop_name: shopName, shop_category: shopCategory } : undefined,
          )
            .then(onSuccess)
            .catch((error: Error) => onError(error.message));
        },
      });
      container.innerHTML = "";
      window.google.accounts.id.renderButton(container, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        width: 320,
      });
    };

    if (window.google) {
      render();
      return;
    }
    const existing = document.getElementById(GOOGLE_SCRIPT_ID);
    if (existing) {
      existing.addEventListener("load", render);
      return () => existing.removeEventListener("load", render);
    }
    const script = document.createElement("script");
    script.id = GOOGLE_SCRIPT_ID;
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = render;
    document.head.appendChild(script);
  }, [asSeller, shopName, shopCategory, onError, onSuccess]);

  if (!GOOGLE_CLIENT_ID) {
    return (
      <p className="google-signin-disabled">
        구글 로그인은 관리자가 GOOGLE_CLIENT_ID 환경변수를 설정하면 활성화됩니다.
      </p>
    );
  }
  return <div ref={containerRef} className="google-signin-button" />;
}

function LoginPage({
  onLoggedIn,
  onGoToSignup,
  onError,
}: {
  onLoggedIn: (auth: AuthResponse) => void;
  onGoToSignup: () => void;
  onError: (message: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: onLoggedIn,
    onError: (error: Error) => onError(error.message),
  });
  return (
    <main className="store-section auth-page">
      <SectionTitle eyebrow="ACCOUNT" title="로그인" />
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
        <label>이메일<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>비밀번호<input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button className="primary dark block" disabled={mutation.isPending}>{mutation.isPending ? "로그인 중…" : "로그인"}</button>
      </form>
      <div className="auth-divider"><span>또는</span></div>
      <GoogleSignInButton onSuccess={onLoggedIn} onError={onError} />
      <p className="auth-switch">아직 계정이 없으신가요? <button className="link" onClick={onGoToSignup}>회원가입</button></p>
    </main>
  );
}

function SignupPage({
  onSignedUp,
  onGoToLogin,
  onError,
}: {
  onSignedUp: (auth: AuthResponse) => void;
  onGoToLogin: () => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState({ email: "", password: "", name: "", phone: "" });
  const [asSeller, setAsSeller] = useState(false);
  const [shopName, setShopName] = useState("");
  const [shopCategory, setShopCategory] = useState("패션");
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const mutation = useMutation({
    mutationFn: () =>
      signup({
        ...form,
        as_seller: asSeller,
        shop_name: asSeller ? shopName : undefined,
        shop_category: asSeller ? shopCategory : undefined,
      } satisfies SignupInput),
    onSuccess: onSignedUp,
    onError: (error: Error) => onError(error.message),
  });
  return (
    <main className="store-section auth-page">
      <SectionTitle eyebrow="ACCOUNT" title="회원가입" />
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
        <label>이메일<input type="email" required value={form.email} onChange={(e) => update("email", e.target.value)} /></label>
        <label>비밀번호(8자 이상)<input type="password" required minLength={8} value={form.password} onChange={(e) => update("password", e.target.value)} /></label>
        <label>이름<input required value={form.name} onChange={(e) => update("name", e.target.value)} /></label>
        <label>연락처<input required value={form.phone} onChange={(e) => update("phone", e.target.value)} /></label>
        <label className="seller-toggle">
          <input type="checkbox" checked={asSeller} onChange={(e) => setAsSeller(e.target.checked)} />
          판매자로 시작하기 (본인 상품을 등록하고 판매 수수료를 냅니다)
        </label>
        {asSeller && (
          <div className="form-grid seller-fields">
            <label>상점명<input required={asSeller} value={shopName} onChange={(e) => setShopName(e.target.value)} /></label>
            <label>카테고리
              <select value={shopCategory} onChange={(e) => setShopCategory(e.target.value)}>
                <option value="패션">패션</option>
                <option value="가방·잡화">가방·잡화</option>
                <option value="슈즈·액세서리">슈즈·액세서리</option>
                <option value="기타">기타</option>
              </select>
            </label>
          </div>
        )}
        <button className="primary dark block" disabled={mutation.isPending}>{mutation.isPending ? "가입 처리 중…" : "회원가입"}</button>
      </form>
      <div className="auth-divider"><span>또는</span></div>
      <GoogleSignInButton asSeller={asSeller} shopName={shopName} shopCategory={shopCategory} onSuccess={onSignedUp} onError={onError} />
      <p className="auth-switch">이미 계정이 있으신가요? <button className="link" onClick={onGoToLogin}>로그인</button></p>
    </main>
  );
}

function ProfilePage({
  auth,
  onUpdated,
  onLogout,
  onError,
  onOpenSellerConsole,
  onOpenAdminConsole,
}: {
  auth: AuthResponse;
  onUpdated: (auth: AuthResponse) => void;
  onLogout: () => void;
  onError: (message: string) => void;
  onOpenSellerConsole: () => void;
  onOpenAdminConsole: () => void;
}) {
  const [shopName, setShopName] = useState("");
  const [shopCategory, setShopCategory] = useState("패션");
  const refreshMe = useMutation({
    mutationFn: () => getMe(auth.access_token),
    onSuccess: (customer) => onUpdated({ ...auth, customer }),
    onError: (error: Error) => onError(error.message),
  });
  const activate = useMutation({
    mutationFn: () => activateSeller(auth.access_token, { shop_name: shopName, shop_category: shopCategory }),
    onSuccess: (customer) => onUpdated({ ...auth, customer }),
    onError: (error: Error) => onError(error.message),
  });
  const { customer } = auth;
  return (
    <main className="store-section profile-page">
      <SectionTitle eyebrow="MY ACCOUNT" title="마이페이지" />
      <div className="profile-card">
        <span className={`role-badge role-${customer.role.toLowerCase()}`}>{roleLabel[customer.role] ?? customer.role}</span>
        <h2>{customer.name}</h2>
        <p>{customer.email} · {customer.phone}</p>
        <div className="profile-actions">
          <button className="link" onClick={() => refreshMe.mutate()} disabled={refreshMe.isPending}>정보 새로고침</button>
          <button className="link" onClick={onLogout}>로그아웃</button>
        </div>
      </div>

      {customer.role === "CONSUMER" && (
        <div className="seller-activate-card">
          <h3>비즈니스로 가입하기</h3>
          <p>본인 상품(옷, 신발 등)을 등록해 판매하고 싶다면 판매자로 전환하세요. 판매 건마다 플랫폼 수수료가 차감됩니다.</p>
          <div className="form-grid">
            <label>상점명<input required value={shopName} onChange={(e) => setShopName(e.target.value)} /></label>
            <label>카테고리
              <select value={shopCategory} onChange={(e) => setShopCategory(e.target.value)}>
                <option value="패션">패션</option>
                <option value="가방·잡화">가방·잡화</option>
                <option value="슈즈·액세서리">슈즈·액세서리</option>
                <option value="기타">기타</option>
              </select>
            </label>
          </div>
          <button
            className="primary dark"
            disabled={activate.isPending || !shopName.trim()}
            onClick={() => activate.mutate()}
          >
            {activate.isPending ? "처리 중…" : "판매자로 활성화"}
          </button>
        </div>
      )}

      {customer.organization && (
        <div className="seller-activate-card">
          <h3>판매자 상점</h3>
          <p><b>{customer.organization.name}</b> · {customer.organization.category}</p>
          <p>플랫폼 수수료율 {Math.round(customer.organization.commission_rate * 100)}% · 상태 {customer.organization.status}</p>
          <button className="primary dark" onClick={onOpenSellerConsole}>판매자 콘솔로 이동</button>
        </div>
      )}

      {customer.is_admin && (
        <div className="seller-activate-card">
          <h3>총관리자</h3>
          <p>마켓플레이스에 입점한 판매자를 조회하고 승인·정지할 수 있습니다.</p>
          <button className="primary dark" onClick={onOpenAdminConsole}>관리자 콘솔로 이동</button>
        </div>
      )}
    </main>
  );
}

function SellerConsolePage({
  auth,
  categories,
  onBack,
  onError,
}: {
  auth: AuthResponse;
  categories: Category[];
  onBack: () => void;
  onError: (message: string) => void;
}) {
  const [tab, setTab] = useState<"dashboard" | "orders" | "inquiries" | "products" | "discord">("dashboard");
  const [showForm, setShowForm] = useState(false);
  const orgId = auth.customer.organization?.id;

  return (
    <main className="store-section profile-page console-page">
      <PageHeader
        eyebrow="SELLER CONSOLE"
        title={auth.customer.organization?.name ?? "판매자 콘솔"}
        onBack={onBack}
        action={tab === "products" ? <button className="primary dark" onClick={() => setShowForm((value) => !value)}>{showForm ? "취소" : "상품 등록"}</button> : undefined}
      />
      <div className="console-tabs">
        <button className={tab === "dashboard" ? "active" : ""} onClick={() => setTab("dashboard")}>오늘의 대시보드</button>
        <button className={tab === "orders" ? "active" : ""} onClick={() => setTab("orders")}>주문 관리</button>
        <button className={tab === "inquiries" ? "active" : ""} onClick={() => setTab("inquiries")}>문의</button>
        <button className={tab === "products" ? "active" : ""} onClick={() => setTab("products")}>상품 관리</button>
        <button className={tab === "discord" ? "active" : ""} onClick={() => setTab("discord")}>디스코드 연동</button>
      </div>

      {tab === "discord" && <SellerDiscordPanel token={auth.access_token} />}

      {tab === "dashboard" && orgId && <SellerDailyDashboard token={auth.access_token} orgId={orgId} />}

      {tab === "orders" && orgId && <SellerOrdersPanel token={auth.access_token} orgId={orgId} />}

      {tab === "inquiries" && orgId && <SellerInquiriesPanel token={auth.access_token} orgId={orgId} />}

      {tab === "products" && (
        <SellerProductsPanel
          token={auth.access_token}
          customerId={auth.customer.id}
          categories={categories}
          showForm={showForm}
          onCloseForm={() => setShowForm(false)}
          onError={onError}
        />
      )}
    </main>
  );
}

// 상품은 항상 소분류(leaf)에 등록 — 대분류는 상품 필터링용일 뿐 상품이 직접 속하지 않음.
// leaf = 이 카테고리를 parent로 둔 다른 카테고리가 없는 카테고리(소분류, 또는 소분류가 없는 "신발" 자신).
function leafCategoriesOf(categories: Category[]) {
  return categories.filter((c) => !categories.some((other) => other.parent_id === c.id));
}

function CategorySelect({ categories, leafCategories, value, onChange }: { categories: Category[]; leafCategories: Category[]; value: string; onChange: (id: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {categories.filter((c) => !c.parent_id).map((parent) => {
        const kids = leafCategories.filter((c) => c.parent_id === parent.id);
        const options = kids.length ? kids : leafCategories.filter((c) => c.id === parent.id);
        return <optgroup key={parent.id} label={parent.name}>{options.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</optgroup>;
      })}
    </select>
  );
}

function ImageUrlListEditor({ images, onChange }: { images: string[]; onChange: (next: string[]) => void }) {
  const update = (index: number, value: string) => onChange(images.map((url, i) => (i === index ? value : url)));
  const remove = (index: number) => onChange(images.filter((_, i) => i !== index));
  return (
    <div className="repeat-field">
      {images.map((url, index) => (
        <div className="repeat-row" key={index}>
          <input placeholder="https://images.example.com/..." value={url} onChange={(e) => update(index, e.target.value)} />
          {images.length > 1 && <button type="button" className="ghost" onClick={() => remove(index)}>삭제</button>}
        </div>
      ))}
      <button type="button" className="link" onClick={() => onChange([...images, ""])}>+ 이미지 URL 추가</button>
    </div>
  );
}

interface VariantDraft { color: string; size: string; stock: string; price: string }

function VariantListEditor({ variants, onChange }: { variants: VariantDraft[]; onChange: (next: VariantDraft[]) => void }) {
  const update = (index: number, key: keyof VariantDraft, value: string) =>
    onChange(variants.map((variant, i) => (i === index ? { ...variant, [key]: value } : variant)));
  const remove = (index: number) => onChange(variants.filter((_, i) => i !== index));
  return (
    <div className="repeat-field">
      {variants.map((variant, index) => (
        <div className="variant-row" key={index}>
          <input placeholder="색상" required value={variant.color} onChange={(e) => update(index, "color", e.target.value)} />
          <input placeholder="사이즈" required value={variant.size} onChange={(e) => update(index, "size", e.target.value)} />
          <input placeholder="재고" type="number" min={0} required value={variant.stock} onChange={(e) => update(index, "stock", e.target.value)} />
          <input placeholder="가격(선택)" type="number" min={1} value={variant.price} onChange={(e) => update(index, "price", e.target.value)} />
          {variants.length > 1 && <button type="button" className="ghost" onClick={() => remove(index)}>삭제</button>}
        </div>
      ))}
      <button type="button" className="link" onClick={() => onChange([...variants, { color: "", size: "", stock: "1", price: "" }])}>+ 옵션 추가</button>
    </div>
  );
}

function SellerProductsPanel({
  token,
  customerId,
  categories,
  showForm,
  onCloseForm,
  onError,
}: {
  token: string;
  customerId: string;
  categories: Category[];
  showForm: boolean;
  onCloseForm: () => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const leafCategories = leafCategoriesOf(categories);
  const emptyForm = { name: "", category_id: leafCategories[0]?.id ?? "", description: "", price: "", compare_at_price: "", material: "", care: "" };
  const [form, setForm] = useState(emptyForm);
  const [images, setImages] = useState<string[]>([""]);
  const [variants, setVariants] = useState<VariantDraft[]>([{ color: "", size: "", stock: "1", price: "" }]);
  const [editingId, setEditingId] = useState<string | null>(null);

  const products = useQuery({
    queryKey: ["seller-products", customerId],
    queryFn: () => getMyProducts(token),
  });

  const create = useMutation({
    mutationFn: () =>
      createMyProduct(token, {
        name: form.name,
        category_id: form.category_id,
        description: form.description,
        material: form.material,
        care: form.care,
        images: images.filter((url) => url.trim()),
        price: Number(form.price),
        compare_at_price: form.compare_at_price ? Number(form.compare_at_price) : undefined,
        variants: variants.map((variant) => ({
          color: variant.color,
          size: variant.size,
          stock: Number(variant.stock),
          price: variant.price ? Number(variant.price) : undefined,
        })),
      } satisfies SellerProductInput),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["seller-products", customerId] });
      onCloseForm();
      setForm(emptyForm);
      setImages([""]);
      setVariants([{ color: "", size: "", stock: "1", price: "" }]);
      // AI 추천 엔진용 색상/스타일 태깅 — best-effort, 실패해도 상품 등록은 이미 끝난 상태.
      tagProductAttributes(created.id).catch(() => {});
    },
    onError: (error: Error) => onError(error.message),
  });

  return (
    <>
      {showForm && (
        <form className="form-grid seller-product-form" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <label>상품명<input required value={form.name} onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))} /></label>
          <label>카테고리<CategorySelect categories={categories} leafCategories={leafCategories} value={form.category_id} onChange={(id) => setForm((c) => ({ ...c, category_id: id }))} /></label>
          <label className="wide">설명<textarea required minLength={5} rows={3} value={form.description} onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))} /></label>
          <label>소재<input value={form.material} onChange={(e) => setForm((c) => ({ ...c, material: e.target.value }))} /></label>
          <label>관리 방법<input value={form.care} onChange={(e) => setForm((c) => ({ ...c, care: e.target.value }))} /></label>
          <label>기준가(원)<input required type="number" min={1} value={form.price} onChange={(e) => setForm((c) => ({ ...c, price: e.target.value }))} /></label>
          <label>정가(할인 전, 선택)<input type="number" min={1} value={form.compare_at_price} onChange={(e) => setForm((c) => ({ ...c, compare_at_price: e.target.value }))} /></label>
          <label className="wide">상품 이미지<ImageUrlListEditor images={images} onChange={setImages} /></label>
          <label className="wide">옵션(색상·사이즈·재고)<VariantListEditor variants={variants} onChange={setVariants} /></label>
          <div className="form-actions wide">
            <button type="button" className="ghost" onClick={onCloseForm}>취소</button>
            <button className="primary dark" disabled={create.isPending}>{create.isPending ? "등록 중…" : "상품 등록"}</button>
          </div>
        </form>
      )}
      <div className="seller-product-list">
        {products.isLoading && <p className="empty">불러오는 중…</p>}
        {products.data?.map((product) => (
          <SellerProductRow
            key={product.id}
            product={product}
            token={token}
            customerId={customerId}
            categories={categories}
            leafCategories={leafCategories}
            editing={editingId === product.id}
            onToggleEdit={() => setEditingId((current) => (current === product.id ? null : product.id))}
            onError={onError}
          />
        ))}
        {!products.isLoading && !products.data?.length && <p className="empty">등록한 상품이 없습니다. 상품 등록 버튼으로 첫 상품을 올려보세요.</p>}
      </div>
    </>
  );
}

function SellerProductRow({
  product,
  token,
  customerId,
  categories,
  leafCategories,
  editing,
  onToggleEdit,
  onError,
}: {
  product: SellerProduct;
  token: string;
  customerId: string;
  categories: Category[];
  leafCategories: Category[];
  editing: boolean;
  onToggleEdit: () => void;
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["seller-products", customerId] });
  const [newVariant, setNewVariant] = useState({ color: "", size: "", stock: "1" });

  const toggleActive = useMutation({
    mutationFn: () =>
      updateMyProduct(token, product.id, {
        name: product.name,
        category_id: product.category_id,
        description: product.description,
        material: product.material,
        care: product.care,
        images: product.images,
        price: product.price,
        compare_at_price: product.compare_at_price ?? undefined,
        is_active: !product.is_active,
      } satisfies SellerProductUpdateInput),
    onSuccess: invalidate,
    onError: (error: Error) => onError(error.message),
  });

  const addVariant = useMutation({
    mutationFn: (input: SellerVariantInput) => createMyProductVariant(token, product.id, input),
    onSuccess: () => {
      invalidate();
      setNewVariant({ color: "", size: "", stock: "1" });
    },
    onError: (error: Error) => onError(error.message),
  });

  const updateVariant = useMutation({
    mutationFn: ({ variantId, stock, price }: { variantId: string; stock: number; price?: number }) =>
      updateMyVariant(token, product.id, variantId, { stock, price }),
    onSuccess: invalidate,
    onError: (error: Error) => onError(error.message),
  });

  const removeVariant = useMutation({
    mutationFn: (variantId: string) => deleteMyProductVariant(token, product.id, variantId),
    onSuccess: invalidate,
    onError: (error: Error) => onError(error.message),
  });

  return (
    <article className="seller-product-row-full">
      <div className="seller-product-summary">
        <img src={product.images[0] ?? product.image} alt={product.name} />
        <div>
          <h3>{product.name} {!product.is_active && <span className="tag-inactive">판매 중지</span>}</h3>
          <small>{won.format(product.price)}{product.compare_at_price ? <> · <del>{won.format(product.compare_at_price)}</del></> : null}</small>
        </div>
        <div className="seller-product-row-actions">
          <button type="button" className="ghost" onClick={onToggleEdit}>{editing ? "닫기" : "수정"}</button>
          <button
            type="button"
            className={product.is_active ? "danger-button" : "primary dark"}
            disabled={toggleActive.isPending}
            onClick={() => toggleActive.mutate()}
          >
            {product.is_active ? "판매 중지" : "판매 재개"}
          </button>
        </div>
      </div>

      {editing && (
        <SellerProductEditForm
          product={product}
          token={token}
          categories={categories}
          leafCategories={leafCategories}
          onSaved={() => { invalidate(); onToggleEdit(); }}
          onCancel={onToggleEdit}
          onError={onError}
        />
      )}

      <div className="seller-variant-list">
        {product.variants.map((variant) => (
          <div className="seller-variant-row" key={variant.id}>
            <span>{variant.color} / {variant.size}</span>
            <label>
              재고
              <input
                type="number"
                min={0}
                defaultValue={variant.stock}
                onBlur={(event) => {
                  const stock = Number(event.target.value);
                  if (!Number.isNaN(stock) && stock !== variant.stock) {
                    updateVariant.mutate({ variantId: variant.id, stock, price: variant.price });
                  }
                }}
              />
            </label>
            <label>
              가격
              <input
                type="number"
                min={1}
                defaultValue={variant.price}
                onBlur={(event) => {
                  const price = Number(event.target.value);
                  if (!Number.isNaN(price) && price > 0 && price !== variant.price) {
                    updateVariant.mutate({ variantId: variant.id, stock: variant.stock, price });
                  }
                }}
              />
            </label>
            {product.variants.length > 1 && (
              <button type="button" className="ghost" disabled={removeVariant.isPending} onClick={() => removeVariant.mutate(variant.id)}>삭제</button>
            )}
          </div>
        ))}
        <div className="seller-variant-row seller-variant-add">
          <input placeholder="색상" value={newVariant.color} onChange={(e) => setNewVariant((c) => ({ ...c, color: e.target.value }))} />
          <input placeholder="사이즈" value={newVariant.size} onChange={(e) => setNewVariant((c) => ({ ...c, size: e.target.value }))} />
          <input placeholder="재고" type="number" min={0} value={newVariant.stock} onChange={(e) => setNewVariant((c) => ({ ...c, stock: e.target.value }))} />
          <button
            type="button"
            className="link"
            disabled={!newVariant.color.trim() || !newVariant.size.trim() || addVariant.isPending}
            onClick={() => addVariant.mutate({ color: newVariant.color, size: newVariant.size, stock: Number(newVariant.stock) || 0 })}
          >
            + 옵션 추가
          </button>
        </div>
      </div>
    </article>
  );
}

function SellerProductEditForm({
  product,
  token,
  categories,
  leafCategories,
  onSaved,
  onCancel,
  onError,
}: {
  product: SellerProduct;
  token: string;
  categories: Category[];
  leafCategories: Category[];
  onSaved: () => void;
  onCancel: () => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState({
    name: product.name,
    category_id: product.category_id,
    description: product.description,
    material: product.material,
    care: product.care,
    price: String(product.price),
    compare_at_price: product.compare_at_price ? String(product.compare_at_price) : "",
  });
  const [images, setImages] = useState<string[]>(product.images.length ? product.images : [""]);

  const save = useMutation({
    mutationFn: () =>
      updateMyProduct(token, product.id, {
        name: form.name,
        category_id: form.category_id,
        description: form.description,
        material: form.material,
        care: form.care,
        images: images.filter((url) => url.trim()),
        price: Number(form.price),
        compare_at_price: form.compare_at_price ? Number(form.compare_at_price) : undefined,
        is_active: product.is_active,
      } satisfies SellerProductUpdateInput),
    onSuccess: onSaved,
    onError: (error: Error) => onError(error.message),
  });

  return (
    <form className="form-grid seller-product-form seller-product-edit-form" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <label>상품명<input required value={form.name} onChange={(e) => setForm((c) => ({ ...c, name: e.target.value }))} /></label>
      <label>카테고리<CategorySelect categories={categories} leafCategories={leafCategories} value={form.category_id} onChange={(id) => setForm((c) => ({ ...c, category_id: id }))} /></label>
      <label className="wide">설명<textarea required minLength={5} rows={3} value={form.description} onChange={(e) => setForm((c) => ({ ...c, description: e.target.value }))} /></label>
      <label>소재<input value={form.material} onChange={(e) => setForm((c) => ({ ...c, material: e.target.value }))} /></label>
      <label>관리 방법<input value={form.care} onChange={(e) => setForm((c) => ({ ...c, care: e.target.value }))} /></label>
      <label>기준가(원)<input required type="number" min={1} value={form.price} onChange={(e) => setForm((c) => ({ ...c, price: e.target.value }))} /></label>
      <label>정가(할인 전, 선택)<input type="number" min={1} value={form.compare_at_price} onChange={(e) => setForm((c) => ({ ...c, compare_at_price: e.target.value }))} /></label>
      <label className="wide">상품 이미지<ImageUrlListEditor images={images} onChange={setImages} /></label>
      <div className="form-actions wide">
        <button type="button" className="ghost" onClick={onCancel}>취소</button>
        <button className="primary dark" disabled={save.isPending}>{save.isPending ? "저장 중…" : "저장"}</button>
      </div>
    </form>
  );
}

function SellerDiscordPanel({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const inviteUrl = (import.meta.env.VITE_DISCORD_INVITE_URL as string | undefined) ?? "";
  const status = useQuery({
    queryKey: ["discord-status"],
    queryFn: () => getDiscordStatus(token),
  });
  const issueCode = useMutation({
    mutationFn: () => createDiscordLinkCode(token),
    onSuccess: (data: DiscordStatus) => queryClient.setQueryData(["discord-status"], data),
  });
  const data = issueCode.data ?? status.data;
  const linked = Boolean(data?.linked);
  const code = issueCode.data?.link_code;

  const copy = (text: string) => navigator.clipboard?.writeText(text).catch(() => undefined);

  return (
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>
          판매자는 <b>디스코드 연동이 필수</b>입니다. 봇을 서버에 초대하고 아래 코드로
          연동하면, 요금제(<b>{data?.plan ?? "FREE"}</b>)에 맞는 채널과 웹훅이 자동으로
          만들어지고 매출·조회수 리포트가 그 서버로 전달됩니다.
        </p>
      </div>

      {!linked && (
        <div
          className="console-card"
          style={{ borderLeft: "3px solid #f472b6", marginBottom: 16 }}
        >
          ⚠️ 아직 디스코드가 연동되지 않았습니다. 아래 3단계를 완료해주세요.
        </div>
      )}
      {linked && (
        <div
          className="console-card"
          style={{ borderLeft: "3px solid #4ade80", marginBottom: 16 }}
        >
          ✅ 연동 완료 · 서버 ID <code>{data?.guild_id}</code>
        </div>
      )}

      <div className="console-grid-two">
        <div className="console-card">
          <h4>1 · 봇 초대</h4>
          {inviteUrl ? (
            <p>
              <a className="primary dark" href={inviteUrl} target="_blank" rel="noreferrer"
                 style={{ display: "inline-block", padding: "8px 14px", borderRadius: 10 }}>
                디스코드 봇 초대하기
              </a>
            </p>
          ) : (
            <p className="empty">
              관리자가 <code>VITE_DISCORD_INVITE_URL</code> 환경변수를 설정하면 초대 버튼이
              표시됩니다.
            </p>
          )}
          <p>봇에 <b>채널 관리·웹훅 관리·메시지 보내기</b> 권한이 필요합니다.</p>
        </div>

        <div className="console-card">
          <h4>2 · 연동 코드 발급</h4>
          <button
            className="primary dark"
            disabled={issueCode.isPending}
            onClick={() => issueCode.mutate()}
          >
            {issueCode.isPending ? "발급 중…" : code ? "코드 다시 발급" : "연동 코드 발급"}
          </button>
          {code && (
            <p style={{ marginTop: 10 }}>
              발급된 코드:{" "}
              <code style={{ fontSize: "1.1em", letterSpacing: "0.1em" }}>{code}</code>{" "}
              <button className="ghost" onClick={() => copy(code)}>복사</button>
              <br />
              <small>서버에서 <code>/실행 코드:{code}</code> 를 입력하세요. (1회용)</small>
            </p>
          )}
        </div>
      </div>

      <div className="console-card" style={{ marginTop: 16 }}>
        <h4>3 · 서버에서 <code>/실행</code> 실행 → 아래 채널이 자동 생성됩니다</h4>
        {status.isLoading && <p className="empty">불러오는 중…</p>}
        <ul>
          {(data?.plan_channels ?? []).map((channel) => (
            <li key={channel.channel_key}>
              <b>#{channel.name}</b>
              {channel.persona ? (
                <>
                  {" "}— <code>{channel.persona}</code> 페르소나
                </>
              ) : (
                <> — 봇 명령용</>
              )}
              <br />
              <small>{channel.topic}</small>
            </li>
          ))}
        </ul>
        {data?.channels?.length ? (
          <p>
            <small>
              현재 생성된 채널 {data.channels.length}개 (웹훅{" "}
              {data.channels.filter((c) => c.webhook_url).length}개 등록됨)
            </small>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function SellerDailyDashboard({ token, orgId }: { token: string; orgId: string }) {
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
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>어제까지의 조회·판매·환불·재고를 코드가 집계하고, AI가 마지막에 재입고 제안을 덧붙입니다.</p>
        <button className="primary dark" disabled={discordMutation.isPending || query.isLoading} onClick={() => discordMutation.mutate()}>
          {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
        </button>
      </div>
      {query.isLoading && <p className="empty">오늘의 데이터를 불러오는 중…</p>}
      {query.isError && <p className="empty">데이터를 불러오지 못했습니다.</p>}
      {snapshot && (
        <>
          <div className="console-stats">
            <article><span>총결제액</span><strong>{won.format(snapshot.revenue.gross_revenue)}</strong></article>
            <article><span>환불액</span><strong>{won.format(snapshot.revenue.refund_amount)}</strong></article>
            <article><span>순매출</span><strong>{won.format(snapshot.revenue.net_revenue)}</strong></article>
            <article><span>주문 수</span><strong>{snapshot.revenue.order_count}건</strong></article>
            <article><span>날짜</span><strong>{snapshot.date}</strong></article>
          </div>
          <div className="console-grid-two">
            <div className="console-card">
              <h4>오늘의 조회</h4>
              <p>최다 조회: <b>{snapshot.highlights.most_viewed?.product_name ?? "없음"}</b>{snapshot.highlights.most_viewed && ` (${snapshot.highlights.most_viewed.views}회)`}</p>
              <p>최소 조회: <b>{snapshot.highlights.least_viewed?.product_name ?? "없음"}</b>{snapshot.highlights.least_viewed && ` (${snapshot.highlights.least_viewed.views}회)`}</p>
            </div>
            <div className="console-card">
              <h4>오늘의 판매·환불</h4>
              <p>최다 판매: <b>{snapshot.highlights.most_purchased?.product_name ?? "없음"}</b>{snapshot.highlights.most_purchased && ` (${snapshot.highlights.most_purchased.units_sold}개)`}</p>
              <p>최다 환불: <b>{snapshot.highlights.most_refunded?.product_name ?? "없음"}</b>{snapshot.highlights.most_refunded && ` (${snapshot.highlights.most_refunded.refund_units}개)`}</p>
            </div>
          </div>
          {(snapshot.highlights.out_of_stock.length > 0 || snapshot.highlights.low_stock.length > 0) && (
            <div className="console-warning">
              {snapshot.highlights.out_of_stock.length > 0 && <p><b>품절:</b> {snapshot.highlights.out_of_stock.map((p) => p.product_name).join(", ")}</p>}
              {snapshot.highlights.low_stock.length > 0 && <p><b>재고 부족:</b> {snapshot.highlights.low_stock.map((p) => `${p.product_name}(${p.stock}개)`).join(", ")}</p>}
            </div>
          )}
          <div className="console-card">
            <h4>AI 리포트 · 재입고 제안</h4>
            <div className="markdown-body"><ReactMarkdown>{report!.report}</ReactMarkdown></div>
            <footer className="console-footnote">{report!.model} · {report!.prompt_source === "langfuse" ? report!.prompt_version ?? "langfuse" : "fallback"} · {report!.discord_sent ? "Discord 전송 완료" : "Discord 미전송"}</footer>
          </div>
        </>
      )}
    </div>
  );
}

function SellerOrdersPanel({ token, orgId }: { token: string; orgId: string }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["seller-orders", orgId],
    queryFn: () => getMyOrders(token),
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["seller-orders", orgId] });
  const cancel = useMutation({
    mutationFn: (orderId: string) => cancelMyOrder(token, orderId),
    onSuccess: invalidate,
  });
  const refund = useMutation({
    mutationFn: (orderId: string) => completeMyOrderRefund(token, orderId),
    onSuccess: invalidate,
  });
  return (
    <div className="console-panel">
      {query.isLoading && <p className="empty">불러오는 중…</p>}
      {!query.isLoading && !query.data?.length && <p className="empty">아직 이 상점 상품으로 들어온 주문이 없습니다.</p>}
      <div className="seller-product-list">
        {query.data?.map((order) => (
          <article className="seller-order-row" key={order.id}>
            <div>
              <h3>{order.items[0]?.product_name}{order.items.length > 1 && ` 외 ${order.items.length - 1}건`}</h3>
              <small>
                {order.id} · {order.recipient} · {order.phone} · ({order.postal_code}) {order.address1} {order.address2}
              </small>
              <small>{statusLabel[order.status] ?? order.status} · {won.format(order.total)}</small>
            </div>
            <div className="seller-order-actions">
              {["PENDING_PAYMENT", "PREPARING"].includes(order.status) && (
                <button disabled={cancel.isPending} onClick={() => cancel.mutate(order.id)}>주문 취소</button>
              )}
              {order.status === "RETURN_REQUESTED" && (
                <button className="primary dark" disabled={refund.isPending} onClick={() => refund.mutate(order.id)}>환불 처리</button>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function SellerInquiriesPanel({ token, orgId }: { token: string; orgId: string }) {
  const query = useQuery({
    queryKey: ["seller-inquiries", orgId],
    queryFn: () => getOrgInquiries(token, orgId),
  });
  return (
    <div className="console-panel">
      {query.isLoading && <p className="empty">불러오는 중…</p>}
      {!query.isLoading && !query.data?.length && <p className="empty">아직 이 상점 상품과 관련된 문의가 없습니다.</p>}
      <div className="seller-product-list">
        {query.data?.map((inquiry) => (
          <article className="seller-product-row" key={inquiry.id}>
            <div>
              <h3>{inquiry.subject}</h3>
              <small>{inquiry.customer_name} · {inquiry.order_id ?? "일반 문의"} · {inquiryStatusLabel[inquiry.status] ?? inquiry.status}</small>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function AdminConsolePage({
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

function PageHeader({
  eyebrow,
  title,
  onBack,
  action,
}: {
  eyebrow: string;
  title: string;
  onBack: () => void;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-header">
      <button className="link back-link" onClick={onBack}>← 마이페이지로</button>
      <div className="page-header-row">
        <SectionTitle eyebrow={eyebrow} title={title} />
        {action}
      </div>
    </div>
  );
}
