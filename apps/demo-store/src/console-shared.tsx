import { gsap } from "gsap";
import { useEffect, useRef } from "react";

export const won = new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 });

export const statusLabel: Record<string, string> = {
  PENDING_PAYMENT: "결제 대기",
  PREPARING: "상품 준비 중",
  SHIPPING: "배송 중",
  DELIVERED: "배송 완료",
  CANCELLED: "주문 취소",
  RETURN_REQUESTED: "반품 접수",
  REFUNDED: "환불 완료",
};

export const inquiryStatusLabel: Record<string, string> = {
  RECEIVED: "접수",
  AI_PROCESSING: "AI 처리 중",
  AUTO_RESOLVED: "AI 자동 해결",
  ESCALATED: "상담원 이관",
  RESOLVED: "해결",
};

// AUTO_RESOLVED/RESOLVED are the only "nothing left to do" states -- RECEIVED,
// AI_PROCESSING, and ESCALATED all still need a seller (or the AI, mid-turn)
// to do something.
export const isInquiryResolved = (status: string) => status === "AUTO_RESOLVED" || status === "RESOLVED";

export function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
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

export function PageHeader({
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
