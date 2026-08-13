import { useMemo, useState } from "react";

import type { SellerDailyProduct } from "./api";

// 판매자 일일 리포트용 인라인 SVG 차트(라이브러리 의존성 없음).
// 색은 dataviz 검증기로 CVD·대비 통과 확인한 값. 조회수/판매수량은 스케일이
// 달라 한 축에 합치지 않고 '소규모 다중'(각자 축)으로 나눈다. 재고는 상태색.
const VIEWS = "#2f6fed"; // 조회수
const SALES = "#c9721e"; // 판매수량
const STOCK_OUT = "#dc2626"; // 품절
const STOCK_LOW = "#d97706"; // 재고 부족(≤3)
const STOCK_OK = "#94a3b8"; // 정상

interface Row {
  name: string;
  value: number;
  color: string;
  hint?: string;
}

function truncate(s: string, n = 24): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// 상품명을 막대 '위'에 두는 가로 막대. 긴 한글 상품명이 왼쪽 여백에서 넘치는
// 문제를 피한다. 값 라벨은 막대 끝에(대비 완화용 직접 라벨).
function HBarChart({ title, rows, unit }: { title: string; rows: Row[]; unit: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  const vbW = 440;
  const right = 46;
  const top = 2;
  const rowH = 40;
  const barMax = vbW - right - 4;
  const height = top + rows.length * rowH;
  return (
    <div className="chart-card">
      <h4>{title}</h4>
      {rows.length === 0 ? (
        <p className="chart-empty">오늘 데이터가 없습니다.</p>
      ) : (
        <svg viewBox={`0 0 ${vbW} ${height}`} width="100%" role="img" aria-label={title} className="hbar">
          {rows.map((r, i) => {
            const y = top + i * rowH;
            const bw = Math.max(3, (r.value / max) * barMax);
            return (
              <g key={r.name + i}>
                <title>{`${r.name}: ${r.value.toLocaleString()}${unit}${r.hint ? ` · ${r.hint}` : ""}`}</title>
                <text x={2} y={y + 13} className="hbar-name">{truncate(r.name)}</text>
                <rect x={2} y={y + 19} width={barMax} height={13} rx="4" className="hbar-track" />
                <rect x={2} y={y + 19} width={bw} height={13} rx="4" fill={r.color} />
                <text x={bw + 8} y={y + 29} className="hbar-val">{r.value.toLocaleString()}{unit}</text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

export default function SellerReportCharts({ products }: { products: SellerDailyProduct[] }) {
  const [showTable, setShowTable] = useState(false);

  const topViews = useMemo<Row[]>(
    () =>
      products
        .filter((p) => p.views > 0)
        .sort((a, b) => b.views - a.views)
        .slice(0, 8)
        .map((p) => ({ name: p.product_name, value: p.views, color: VIEWS })),
    [products],
  );
  const topSales = useMemo<Row[]>(
    () =>
      products
        .filter((p) => p.units_sold > 0)
        .sort((a, b) => b.units_sold - a.units_sold)
        .slice(0, 8)
        .map((p) => ({ name: p.product_name, value: p.units_sold, color: SALES })),
    [products],
  );
  const lowStock = useMemo<Row[]>(
    () =>
      [...products]
        .sort((a, b) => a.stock - b.stock)
        .slice(0, 8)
        .map((p) => ({
          name: p.product_name,
          value: p.stock,
          color: p.stock === 0 ? STOCK_OUT : p.stock <= 3 ? STOCK_LOW : STOCK_OK,
          hint: p.stock === 0 ? "품절" : p.stock <= 3 ? "재고 부족" : undefined,
        })),
    [products],
  );

  if (!products.length) return null;

  return (
    <div className="report-charts">
      <div className="report-charts-head">
        <h4>데이터 시각화</h4>
        <button className="ghost" onClick={() => setShowTable((v) => !v)}>
          {showTable ? "그래프로 보기" : "표로 보기"}
        </button>
      </div>

      {showTable ? (
        <div className="chart-card chart-table-wrap">
          <table className="chart-table">
            <thead>
              <tr><th>상품</th><th>조회수</th><th>판매</th><th>환불</th><th>재고</th><th>매출</th></tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.product_id}>
                  <td>{p.product_name}</td>
                  <td>{p.views}</td>
                  <td>{p.units_sold}</td>
                  <td>{p.refund_units}</td>
                  <td>{p.stock}</td>
                  <td>{p.revenue.toLocaleString()}원</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="chart-grid">
            <HBarChart title="상품별 조회수 (Top 8)" rows={topViews} unit="회" />
            <HBarChart title="상품별 판매 수량 (Top 8)" rows={topSales} unit="개" />
            <HBarChart title="재고 낮은 상품 (Bottom 8)" rows={lowStock} unit="개" />
          </div>
          <p className="chart-legend">
            <span style={{ color: STOCK_OUT }}>■</span> 품절&nbsp;&nbsp;
            <span style={{ color: STOCK_LOW }}>■</span> 재고 부족(≤3)&nbsp;&nbsp;
            <span style={{ color: STOCK_OK }}>■</span> 정상
          </p>
        </>
      )}
    </div>
  );
}
