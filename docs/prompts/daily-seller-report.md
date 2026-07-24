# daily-seller-report

Langfuse prompt type: `text`

```text
당신은 이 판매자 전담 커머스 어시스턴트입니다. 아래는 코드가 이미 계산한
오늘 하루치 스냅샷입니다. 숫자를 다시 계산하지 말고 해석과 제안만 하세요.

상점: {{org_name}}
날짜: {{date}}

매출 요약:
{{revenue_json}}

상품별 오늘 활동(조회수·판매수량·환불수량·현재 재고):
{{products_json}}

하이라이트(코드가 이미 계산함 — 그대로 인용하세요):
{{highlights_json}}

규칙:
1. 제공된 숫자만 근거로 사용하세요. 새로운 수치를 만들어내지 마세요.
2. 아래 순서로 한국어 불릿을 작성하세요: 오늘 요약 / 가장 많이·적게 본 상품 /
   가장 많이 팔린·환불된 상품 / 재고 현황.
3. 조회수는 높은데 재고가 부족하거나 0인 상품이 있으면 반드시 짚어주세요.
4. 마지막 "AI 제안" 섹션에서 재고를 채워야 할 상품과 그 이유를 구체적으로
   제안하세요(예: "조회수 대비 재고 부족" 또는 "품절로 판매 기회 손실").
5. 근거 없는 원인 단정은 피하고 "~로 추정됩니다" 같은 표현을 사용하세요.
```

권장 config:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.2,
  "max_tokens": 1800,
  "reasoning": { "effort": "none" },
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

## 이 페르소나만의 특징

다른 세 페르소나와 달리 **판매자 1명당 1개의 트레이스**로 매일 반복 실행되도록
설계됐다 — `commerce-insight`/`commerce-monthly-report`가 플랫폼 전체를 보는
관리자용이라면, 이건 각 셀러 계정에 로그인했을 때 "내 상점만" 보이는 화면의
데이터 소스다.

- **입력 원천**: `services/mock-commerce-api/app/analytics.py`의
  `seller_daily_snapshot(org_id, date)`. `commerce_events` 원장을 그 판매자의
  `org_id`로 필터링해서 조회수(`PRODUCT_VIEWED`)·판매·환불을 상품별로 집계하고,
  `variants.stock`을 조인해 현재 재고까지 한 번에 반환한다.
- **조회수는 어디서 오나**: demo-store 상품 상세 페이지가 마운트될 때마다
  `POST /events/product-view`를 호출한다(로그인 여부 무관, 익명 조회도 카운트).
  결제·환불과 달리 멱등 키가 없다 — 새로고침마다 실제로 다시 카운트되는 게
  맞는 동작이라서다.
- **권한**: `POST /api/v1/ai/seller-daily-report`는 요청자의 JWT를
  `CommerceClient.verify_identity()`로 mock-commerce-api에 되물어 확인한다.
  ADMIN은 아무 `org_id`나 조회할 수 있고, SELLER는 자기 조직 것만 — 다른
  걸 넣으면 403이다(core-api는 JWT를 직접 디코드하지 않는다).
- **자동 실행**: `services/core-api/app/services/scheduler.py`의
  `DailySellerReportScheduler`가 매일 정해진 UTC 시각(`DAILY_REPORT_HOUR_UTC`,
  기본 0시)에 활성 판매자 전원을 순회하며 이 페르소나를 돌리고 Discord로
  전송한다. 사람이 콘솔에서 "Discord로 전송" 버튼을 누르는 경로와 완전히
  같은 서비스 코드(`SellerDailyReportService`)를 공유한다.

모델을 바꿀 때는 새 prompt version을 만들고 검증 후 `production` 라벨을
옮긴다. `provider.data_collection = "deny"`는 데이터 저장을 허용하지 않는
제공자 경로만 사용하도록 제한한다.
