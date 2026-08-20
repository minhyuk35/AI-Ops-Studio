import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";

import SellerReportCharts, { DailyRevenueTrendChart } from "./SellerCharts";
import type { Category } from "@ai-ops/shared-types";
import {
  AuthResponse,
  cancelMyOrder,
  completeMyOrderRefund,
  createDiscordLinkCode,
  createMyProduct,
  createMyProductVariant,
  deleteMyProductVariant,
  DiscordStatus,
  getDiscordStatus,
  getMyOrders,
  getMyProducts,
  getOrgInquiries,
  getSellerDailyReport,
  getSellerDailySeries,
  getUploadStatus,
  SellerDailyReport,
  SellerProduct,
  SellerProductInput,
  SellerProductUpdateInput,
  SellerVariantInput,
  sendDiscordTestNotification,
  tagProductAttributes,
  updateMyProduct,
  updateMyVariant,
  uploadProductImage,
} from "./api";
import { inquiryStatusLabel, PageHeader, statusLabel, won } from "./console-shared";

export default function SellerConsolePage({
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

function ImageUrlListEditor({
  images,
  onChange,
  token,
  onError,
}: {
  images: string[];
  onChange: (next: string[]) => void;
  token?: string;
  onError?: (message: string) => void;
}) {
  const uploadStatus = useQuery({
    queryKey: ["upload-status"],
    queryFn: getUploadStatus,
    staleTime: 5 * 60 * 1000,
  });
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null);
  const update = (index: number, value: string) => onChange(images.map((url, i) => (i === index ? value : url)));
  const remove = (index: number) => onChange(images.filter((_, i) => i !== index));

  const handleFile = async (index: number, file: File | undefined) => {
    if (!file || !token) return;
    setUploadingIndex(index);
    try {
      const { url } = await uploadProductImage(token, file);
      update(index, url);
    } catch (error) {
      onError?.((error as Error).message);
    } finally {
      setUploadingIndex(null);
    }
  };

  return (
    <div className="repeat-field">
      {images.map((url, index) => (
        <div className="repeat-row" key={index}>
          <input placeholder="https://images.example.com/..." value={url} onChange={(e) => update(index, e.target.value)} />
          {uploadStatus.data?.enabled && token && (
            <label className="ghost image-upload-button">
              {uploadingIndex === index ? "업로드 중…" : "파일 업로드"}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                hidden
                disabled={uploadingIndex !== null}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  void handleFile(index, file);
                }}
              />
            </label>
          )}
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
          <label className="wide">상품 이미지<ImageUrlListEditor images={images} onChange={setImages} token={token} onError={onError} /></label>
          <label className="wide">옵션(색상·사이즈·재고)<VariantListEditor variants={variants} onChange={setVariants} /></label>
          <div className="form-actions wide">
            <button type="button" className="ghost" onClick={onCloseForm}>취소</button>
            <button className="primary dark" disabled={create.isPending}>{create.isPending ? "등록 중…" : "상품 등록"}</button>
          </div>
        </form>
      )}
      {products.isLoading && <p className="empty">불러오는 중…</p>}
      {products.isError && (
        <p className="empty">
          상품을 불러오지 못했습니다({(products.error as Error).message}).{" "}
          <button className="link" onClick={() => products.refetch()}>다시 시도</button>
        </p>
      )}
      {!products.isLoading && !products.isError && !products.data?.length && <p className="empty">등록한 상품이 없습니다. 상품 등록 버튼으로 첫 상품을 올려보세요.</p>}
      {!!products.data?.length && (
        <div className="seller-product-list">
          {products.data.map((product) => (
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
        </div>
      )}
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
      <label className="wide">상품 이미지<ImageUrlListEditor images={images} onChange={setImages} token={token} onError={onError} /></label>
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
  const testNotification = useMutation({
    mutationFn: () => sendDiscordTestNotification(token),
  });
  const data = issueCode.data ?? status.data;
  const linked = Boolean(data?.linked);
  const code = issueCode.data?.link_code;

  const copy = (text: string) => navigator.clipboard?.writeText(text).catch(() => undefined);

  return (
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>
          판매자는 <b>디스코드 연동이 필수</b>입니다(계정당 서버 1개만 연동 가능). 봇을 서버에
          초대하고 아래 코드로 연동하면, 요금제(<b>{data?.plan ?? "FREE"}</b>)에 맞는 채널과
          웹훅이 자동으로 만들어지고 매출·조회수 리포트가 그 서버로 전달됩니다.
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
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
            <span>✅ 연동 완료 · 서버 ID <code>{data?.guild_id}</code></span>
            <button
              className="primary dark"
              disabled={testNotification.isPending}
              onClick={() => testNotification.mutate()}
            >
              {testNotification.isPending ? "전송 중…" : "테스트 알림 보내기"}
            </button>
          </div>
          {testNotification.isSuccess && (
            <p style={{ marginTop: 8, color: "#4ade80" }}>
              ✓ #{testNotification.data.channel_name} 채널로 전송했습니다 — Discord에서 확인해보세요.
            </p>
          )}
          {testNotification.isError && (
            <p style={{ marginTop: 8, color: "#f87171" }}>{(testNotification.error as Error).message}</p>
          )}
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
          {issueCode.isError && (
            <p style={{ marginTop: 10, color: "#f87171" }}>{(issueCode.error as Error).message}</p>
          )}
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

function CompareBadge({ pct, label }: { pct: number | null | undefined; label: string }) {
  if (pct === null || pct === undefined) {
    return <span className="compare-badge flat" title={`비교할 ${label} 데이터가 없습니다`}>—</span>;
  }
  const dir = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "–";
  return (
    <span className={`compare-badge ${dir}`} title={`${label} 대비`}>
      {arrow} {Math.abs(pct)}%
    </span>
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
  const seriesQuery = useQuery({
    queryKey: ["seller-daily-series", orgId],
    queryFn: () => getSellerDailySeries(token, 60),
  });
  const report: SellerDailyReport | undefined = discordMutation.data ?? query.data;
  const snapshot = report?.snapshot;

  const { thisMonth, lastMonth, thisMonthLabel, lastMonthLabel } = useMemo(() => {
    const points = seriesQuery.data ?? [];
    const months = Array.from(new Set(points.map((p) => p.date.slice(0, 7)))).sort();
    const current = months[months.length - 1];
    const previous = months[months.length - 2];
    return {
      thisMonth: current ? points.filter((p) => p.date.slice(0, 7) === current) : [],
      lastMonth: previous ? points.filter((p) => p.date.slice(0, 7) === previous) : [],
      thisMonthLabel: current ?? "",
      lastMonthLabel: previous ?? "",
    };
  }, [seriesQuery.data]);

  return (
    <div className="console-panel">
      <div className="console-panel-heading">
        <p>어제까지의 조회·판매·환불·재고를 코드가 집계하고, AI가 마지막에 재입고 제안을 덧붙입니다.</p>
        <button className="primary dark" disabled={discordMutation.isPending || query.isLoading} onClick={() => discordMutation.mutate()}>
          {discordMutation.isPending ? "전송 중…" : "Discord로 전송"}
        </button>
      </div>
      {query.isLoading && <p className="empty">오늘의 데이터를 불러오는 중…</p>}
      {query.isError && (
        <p className="empty">
          데이터를 불러오지 못했습니다({(query.error as Error).message}).{" "}
          <button className="link" onClick={() => query.refetch()}>다시 시도</button>
        </p>
      )}
      {snapshot && (
        <>
          <div className="console-stats">
            <article>
              <span>총결제액</span>
              <strong>{won.format(snapshot.revenue.gross_revenue)}</strong>
              <CompareBadge pct={snapshot.day_over_day_change?.gross_revenue_pct} label="전날" />
            </article>
            <article><span>환불액</span><strong>{won.format(snapshot.revenue.refund_amount)}</strong></article>
            <article>
              <span>순매출</span>
              <strong>{won.format(snapshot.revenue.net_revenue)}</strong>
              <CompareBadge pct={snapshot.day_over_day_change?.net_revenue_pct} label="전날" />
            </article>
            <article>
              <span>주문 수</span>
              <strong>{snapshot.revenue.order_count}건</strong>
              <CompareBadge pct={snapshot.day_over_day_change?.order_count_pct} label="전날" />
            </article>
            <article><span>날짜</span><strong>{snapshot.date}</strong></article>
          </div>
          {snapshot.previous_day && (
            <p className="empty" style={{ marginTop: -6 }}>
              전날({snapshot.previous_day.date}) 총결제액 {won.format(snapshot.previous_day.gross_revenue)} 대비 비교
            </p>
          )}

          {snapshot.month_to_date && (
            <div className="console-card" style={{ marginTop: 14 }}>
              <h4>이번 달 vs 지난달 ({snapshot.month_to_date.period})</h4>
              {snapshot.month_to_date.period_in_progress && (
                <p className="empty" style={{ marginTop: -4 }}>
                  이번 달은 아직 {snapshot.month_to_date.days_elapsed}일차라 지난달 전체 누적과
                  단순 비교하면 낮게 보일 수 있습니다 — 참고용으로 봐주세요.
                </p>
              )}
              <div className="console-stats">
                <article>
                  <span>총결제액</span>
                  <strong>{won.format(snapshot.month_to_date.gross_revenue)}</strong>
                  <CompareBadge pct={snapshot.month_to_date.change?.gross_revenue_pct} label="지난달" />
                </article>
                <article>
                  <span>순매출</span>
                  <strong>{won.format(snapshot.month_to_date.net_revenue)}</strong>
                  <CompareBadge pct={snapshot.month_to_date.change?.net_revenue_pct} label="지난달" />
                </article>
                <article>
                  <span>주문 수</span>
                  <strong>{snapshot.month_to_date.order_count}건</strong>
                  <CompareBadge pct={snapshot.month_to_date.change?.order_count_pct} label="지난달" />
                </article>
                <article>
                  <span>객단가</span>
                  <strong>{won.format(snapshot.month_to_date.average_order_value)}</strong>
                  <CompareBadge pct={snapshot.month_to_date.change?.average_order_value_pct} label="지난달" />
                </article>
              </div>
              {snapshot.month_to_date.previous_period && (
                <p className="empty" style={{ marginBottom: 0 }}>
                  지난달({snapshot.month_to_date.previous_period.period}) 총결제액{" "}
                  {won.format(snapshot.month_to_date.previous_period.gross_revenue)} 대비 비교
                </p>
              )}
            </div>
          )}

          {(thisMonth.length > 0 || lastMonth.length > 0) && (
            <div className="trend-grid-two">
              {thisMonth.length > 0 && (
                <DailyRevenueTrendChart title={`이번 달 일별 매출 추이 (${thisMonthLabel})`} points={thisMonth} color="#2f6fed" />
              )}
              {lastMonth.length > 0 && (
                <DailyRevenueTrendChart title={`지난달 일별 매출 추이 (${lastMonthLabel})`} points={lastMonth} color="#94a3b8" />
              )}
            </div>
          )}

          <SellerReportCharts products={snapshot.products} />
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
      {query.isError && (
        <p className="empty">
          주문을 불러오지 못했습니다({(query.error as Error).message}).{" "}
          <button className="link" onClick={() => query.refetch()}>다시 시도</button>
        </p>
      )}
      {!query.isLoading && !query.isError && !query.data?.length && <p className="empty">아직 이 상점 상품으로 들어온 주문이 없습니다.</p>}
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
      <div className="console-panel-heading">
        <p>AI가 문의를 어떻게 분류·처리하는지 궁금하다면{" "}
          <a href="/guide/inquiry-guide.html" target="_blank" rel="noreferrer">AI 문의 처리 가이드</a>를 참고하세요.</p>
      </div>
      {query.isLoading && <p className="empty">불러오는 중…</p>}
      {query.isError && (
        <p className="empty">
          문의를 불러오지 못했습니다({(query.error as Error).message}).{" "}
          <button className="link" onClick={() => query.refetch()}>다시 시도</button>
        </p>
      )}
      {!query.isLoading && !query.isError && !query.data?.length && <p className="empty">아직 이 상점 상품과 관련된 문의가 없습니다.</p>}
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
