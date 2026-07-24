import type { Cart, Category, Inquiry, Order, Product, ProductDetail } from "@ai-ops/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { FormEvent, lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

gsap.registerPlugin(ScrollTrigger);

import {
  activateSeller,
  addCartItem,
  askSupport,
  AuthResponse,
  cancelOrder,
  confirmPayment,
  createMyProduct,
  createOrder,
  deleteCartItem,
  getCart,
  getCategories,
  getInquiries,
  getInquiry,
  getMe,
  getMyProducts,
  getOrder,
  getOrders,
  getOrganizations,
  getProduct,
  getProducts,
  googleAuth,
  login,
  OrganizationSummary,
  recordProductView,
  returnOrder,
  SellerProduct,
  SellerProductInput,
  signup,
  SignupInput,
  updateCartItem,
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
  | "admin";
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

// three.js is a heavy dependency (~500kB) only needed for the home hero, so
// it's code-split into its own chunk instead of bloating every route.
const ThreeHero = lazy(() => import("./ThreeHero").then((module) => ({ default: module.ThreeHero })));

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
        <div className="header-actions">
          {auth ? (
            <button className="account-button" onClick={() => setView("profile")}>{auth.customer.name}</button>
          ) : (
            <button className="account-button" onClick={() => setView("login")}>로그인</button>
          )}
          <button className="cart-button" onClick={() => setView("cart")}>BAG <b>{cart.data?.item_count ?? 0}</b></button>
        </div>
      </header>

      <Marquee text="NEW SEASON — MINIMAL SILHOUETTE — MONOCHROME — EVERYDAY MARKET — " />

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
      // The hero heading is a photo showing through its own letter shapes
      // (background-clip: text) — this slowly pans that photo so the effect
      // reads as alive rather than a static image crop.
      gsap.to(".hero-heading", {
        backgroundPositionX: "78%",
        duration: 10,
        ease: "sine.inOut",
        repeat: -1,
        yoyo: true,
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
      <Suspense fallback={null}>
        <ThreeHero />
      </Suspense>
      <div className="hero-content">
        <p className="eyebrow hero-reveal">NEW SEASON · 2026</p>
        <h1 className="hero-heading hero-reveal">매일의 옷을<br />조금 더 선명하게.</h1>
        <p className="hero-reveal">오래 입을 수 있는 소재와 절제된 실루엣을 고릅니다.</p>
        <MagneticButton className="primary hero-reveal" onClick={onShop}>컬렉션 보기</MagneticButton>
      </div>
      <div className="hero-index hero-reveal" aria-hidden="true"><span>SHOP</span><span>·</span><span>SS 26</span></div>
    </section>

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

function Catalog(props: { products: Product[]; categories: { slug: string; name: string }[]; selectedCategory: string; sort: string; inStock: boolean; search: string; onCategory: (v: string) => void; onSort: (v: string) => void; onInStock: (v: boolean) => void; onProduct: (p: Product) => void }) {
  return <main className="store-section catalog-page"><SectionTitle eyebrow="SHOP" title={props.search ? `“${props.search}” 검색 결과` : "전체 상품"} />
    <div className="catalog-tools"><div className="category-tabs"><button className={!props.selectedCategory ? "active" : ""} onClick={() => props.onCategory("")}>전체</button>{props.categories.map((item) => <button className={props.selectedCategory === item.slug ? "active" : ""} key={item.slug} onClick={() => props.onCategory(item.slug)}>{item.name}</button>)}</div>
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

function ProductPage({ product, variantId, onVariant, onAdd, onBuy }: { product: ProductDetail; variantId: string; onVariant: (id: string) => void; onAdd: () => void; onBuy: () => void }) {
  useEffect(() => {
    recordProductView(product.id).catch(() => {});
  }, [product.id]);
  return <main className="product-page"><div className="product-gallery"><img src={product.image} alt={product.name} /></div><div className="product-info"><small>{product.brand} · {product.category_name}</small><h1>{product.name}</h1><p className="rating">★ {product.rating} · 리뷰 {product.review_count}개</p><div className="product-price">{product.compare_at_price && <del>{won.format(product.compare_at_price)}</del>}<strong>{won.format(product.price)}</strong></div><p className="description">{product.description}</p><fieldset><legend>옵션 선택</legend>{product.variants.map((variant) => <button type="button" disabled={!variant.stock} className={variantId === variant.id ? "selected" : ""} key={variant.id} onClick={() => onVariant(variant.id)}>{variant.color} / {variant.size}{!variant.stock && " · 품절"}</button>)}</fieldset><div className="purchase-actions"><button onClick={onAdd}>장바구니</button><button className="dark" onClick={onBuy}>바로 구매</button></div><dl className="policy-list"><div><dt>배송</dt><dd>{product.shipping.estimated_days} · {won.format(product.shipping.fee)} · {won.format(product.shipping.free_threshold)} 이상 무료</dd></div><div><dt>반품</dt><dd>수령 후 {product.return_policy.window_days}일 이내 · 단순 변심 {won.format(product.return_policy.return_fee)}</dd></div><div><dt>소재</dt><dd>{product.material}</dd></div><div><dt>관리</dt><dd>{product.care}</dd></div></dl></div></main>;
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

function OrderPage({ order, onCancel, onReturn }: { order: Order; onCancel: () => void; onReturn: () => void }) { return <main className="store-section order-detail"><SectionTitle eyebrow={order.id} title={statusLabel[order.status] ?? order.status} /><div className="order-columns"><section><h2>주문 상품</h2>{order.items.map((item) => <article key={item.id}><div><b>{item.product_name}</b><span>{item.option_text} · {item.quantity}개</span></div><strong>{won.format(item.line_total)}</strong></article>)}</section><aside className="summary"><h2>결제 정보</h2><p><span>상품금액</span><b>{won.format(order.subtotal)}</b></p><p><span>할인</span><b>−{won.format(order.discount)}</b></p><p><span>배송비</span><b>{won.format(order.shipping_fee)}</b></p><p className="total"><span>결제금액</span><strong>{won.format(order.total)}</strong></p></aside></div><section className="shipment"><h2>배송 정보</h2><div className="timeline"><i className="done" /><i className={order.status !== "PENDING_PAYMENT" ? "done" : ""} /><i className={["SHIPPING", "DELIVERED"].includes(order.status) ? "done" : ""} /><i className={order.status === "DELIVERED" ? "done" : ""} /></div><div className="timeline-labels"><span>주문접수</span><span>상품준비</span><span>배송중</span><span>배송완료</span></div><p>{order.shipment?.carrier ?? "택배사 배정 전"} · {order.shipment?.tracking_number ?? "송장번호 준비 중"} · 도착 예정 {order.shipment?.eta ?? "확인 중"}</p></section><section className="address"><h2>받는 분</h2><p>{order.recipient} · {order.phone}</p><p>({order.postal_code}) {order.address1} {order.address2}</p></section><div className="claim-actions">{["PENDING_PAYMENT", "PREPARING"].includes(order.status) && <button onClick={onCancel}>주문 취소</button>}{order.status === "DELIVERED" && <button onClick={onReturn}>반품 신청</button>}</div>{order.claims.length > 0 && <section><h2>취소·반품 내역</h2>{order.claims.map((claim) => <p key={claim.id}>{claim.type} · {claim.status} · 환불 예정 {won.format(claim.refund_amount)}</p>)}</section>}</main>; }

function InquiryPage({ inquiries, selected, onSelect }: { inquiries: Inquiry[]; selected?: Inquiry; onSelect: (id: string) => void }) { return <main className="store-section"><SectionTitle eyebrow="SUPPORT" title="문의 내역" /><div className="inquiry-layout"><div className="inquiry-list">{inquiries.map((item) => <button key={item.id} onClick={() => onSelect(item.id)}><span>{item.category}</span><div><b>{item.subject}</b><small>{item.status} · 메시지 {item.message_count ?? 0}개</small></div></button>)}{!inquiries.length && <div className="empty">아직 문의 내역이 없습니다. 오른쪽 아래 AI 고객지원을 이용해보세요.</div>}</div>{selected && <section className="conversation"><h2>{selected.subject}</h2>{selected.messages?.map((message) => <div className={`bubble ${message.role}`} key={message.id}><b>{message.role === "user" ? "나" : "AI 고객지원"}</b><div className="markdown-body"><ReactMarkdown>{message.content}</ReactMarkdown></div><small>{new Date(message.created_at).toLocaleString("ko-KR")}</small></div>)}</section>}</div></main>; }

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
      <p className="demo-note">데모 계정: demo@example.com / demo1234</p>
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
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    category_id: categories[0]?.id ?? "cat_fashion",
    description: "",
    price: "",
    color: "",
    size: "",
    stock: "1",
  });
  const products = useQuery({
    queryKey: ["seller-products", auth.customer.id],
    queryFn: () => getMyProducts(auth.access_token),
  });
  const create = useMutation({
    mutationFn: () =>
      createMyProduct(auth.access_token, {
        name: form.name,
        category_id: form.category_id,
        description: form.description,
        price: Number(form.price),
        color: form.color,
        size: form.size,
        stock: Number(form.stock),
      } satisfies SellerProductInput),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["seller-products", auth.customer.id] });
      setShowForm(false);
      setForm({ name: "", category_id: categories[0]?.id ?? "cat_fashion", description: "", price: "", color: "", size: "", stock: "1" });
    },
    onError: (error: Error) => onError(error.message),
  });
  const updateStock = useMutation({
    mutationFn: ({ product, stock }: { product: SellerProduct; stock: number }) =>
      updateMyVariant(auth.access_token, product.id, product.variants[0].id, { stock }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["seller-products", auth.customer.id] }),
    onError: (error: Error) => onError(error.message),
  });
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <main className="store-section profile-page">
      <PageHeader
        eyebrow="SELLER CONSOLE"
        title={auth.customer.organization?.name ?? "판매자 콘솔"}
        onBack={onBack}
        action={<button className="primary dark" onClick={() => setShowForm((value) => !value)}>{showForm ? "취소" : "상품 등록"}</button>}
      />
      {showForm && (
        <form
          className="auth-form seller-product-form"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <label>상품명<input required value={form.name} onChange={(e) => update("name", e.target.value)} /></label>
          <label>카테고리
            <select value={form.category_id} onChange={(e) => update("category_id", e.target.value)}>
              {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select>
          </label>
          <label>설명<textarea required minLength={5} rows={3} value={form.description} onChange={(e) => update("description", e.target.value)} /></label>
          <label>가격(원)<input required type="number" min={1} value={form.price} onChange={(e) => update("price", e.target.value)} /></label>
          <label>색상<input required value={form.color} onChange={(e) => update("color", e.target.value)} /></label>
          <label>사이즈<input required value={form.size} onChange={(e) => update("size", e.target.value)} /></label>
          <label>초기 재고<input required type="number" min={0} value={form.stock} onChange={(e) => update("stock", e.target.value)} /></label>
          <button className="primary dark block" disabled={create.isPending}>{create.isPending ? "등록 중…" : "상품 등록"}</button>
        </form>
      )}
      <div className="seller-product-list">
        {products.isLoading && <p className="empty">불러오는 중…</p>}
        {products.data?.map((product) => (
          <article className="seller-product-row" key={product.id}>
            <img src={product.image} alt={product.name} />
            <div>
              <h3>{product.name}</h3>
              <small>{product.variants[0]?.color} / {product.variants[0]?.size} · {won.format(product.price)}</small>
            </div>
            <label className="seller-stock-field">
              재고
              <input
                type="number"
                min={0}
                defaultValue={product.variants[0]?.stock ?? 0}
                onBlur={(event) => {
                  const stock = Number(event.target.value);
                  if (!Number.isNaN(stock) && stock !== product.variants[0]?.stock) {
                    updateStock.mutate({ product, stock });
                  }
                }}
              />
            </label>
          </article>
        ))}
        {!products.isLoading && !products.data?.length && <p className="empty">등록한 상품이 없습니다. 상품 등록 버튼으로 첫 상품을 올려보세요.</p>}
      </div>
    </main>
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
  const organizations = useQuery({
    queryKey: ["admin-organizations"],
    queryFn: () => getOrganizations(auth.access_token),
  });
  const toggleStatus = useMutation({
    mutationFn: (org: OrganizationSummary) =>
      updateOrganizationStatus(auth.access_token, org.id, org.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-organizations"] }),
    onError: (error: Error) => onError(error.message),
  });

  return (
    <main className="store-section profile-page admin-console">
      <PageHeader eyebrow="ADMIN CONSOLE" title="판매자 관리" onBack={onBack} />
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
    </main>
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
