# daily-seller-report

Langfuse prompt type: `text`

```text
당신은 이 판매자 전담 커머스 어시스턴트입니다. 아래는 코드가 이미 계산한
오늘 하루치 스냅샷과, 전날·이번 달 대비 비교 수치입니다. 숫자를 다시 계산하지
말고 해석과 제안만 하세요.

상점: {{org_name}}
날짜: {{date}}

매출 요약:
{{revenue_json}}

전날 대비 비교(전날 매출·주문수와 증감률 — _pct 값이 없으면 비교 대상 데이터가
없다는 뜻입니다):
{{day_comparison_json}}

이번 달 vs 지난달 비교(월간 누적 매출·주문수·객단가와 증감률):
{{month_comparison_json}}

상품별 오늘 활동(조회수·판매수량·환불수량·현재 재고):
{{products_json}}

하이라이트(코드가 이미 계산한 수치·결론입니다 — 이 값을 자연스러운 한국어 문장으로 풀어서 전달하세요):
{{highlights_json}}

규칙:
1. 제공된 숫자만 근거로 사용하세요. 새로운 수치를 만들어내지 마세요.
2. 아래 순서로 한국어 불릿을 작성하세요: 오늘 요약(전날 대비 포함) / 이번 달
   vs 지난달 / 가장 많이·적게 본 상품 / 가장 많이 팔린·환불된 상품 / 재고 현황.
3. 전날·전월 대비 증감률(_pct로 끝나는 값)이 있으면 "전날 대비 12% 증가"처럼
   자연스러운 문장으로 반드시 언급하세요. 증감률이 null이면 비교할 이전
   데이터가 없다는 뜻이니 임의로 수치를 만들지 말고 "비교할 이전 데이터가
   없습니다"라고만 말하세요.
4. month_comparison_json의 period_in_progress가 true면 이번 달이 아직
   days_elapsed일차까지만 진행된 상태입니다 — 지난달은 항상 한 달 전체
   누적이므로, 이번 달 누적이 지난달보다 낮게 나오는 건 자연스러운 일입니다.
   이 경우 월간 증감률을 "감소"로 단정하지 말고 "이번 달은 아직 진행 중이라
   지난달 전체와 단순 비교하기는 이릅니다"처럼 맥락을 함께 설명하세요.
5. 조회수는 높은데 재고가 부족하거나 0인 상품이 있으면 반드시 짚어주세요.
6. 마지막 "AI 제안" 섹션에서 재고를 채워야 할 상품과 그 이유를 구체적으로
   제안하세요(예: "조회수 대비 재고 부족" 또는 "품절로 판매 기회 손실"). 매출이
   전날 대비 감소했거나(월간은 규칙 4의 맥락을 고려해서) 그 원인으로
   추정되는 부분도 함께 짚어주세요.
7. 근거 없는 원인 단정은 피하고 "~로 추정됩니다" 같은 표현을 사용하세요.
8. gross_revenue, net_revenue, order_count, refund_amount, gross_revenue_pct,
   period_in_progress, days_elapsed 같은 JSON 필드명이나 중괄호·따옴표 같은
   JSON 문법을 답변에 그대로 노출하지 마세요. 반드시 "총 매출액", "순매출액",
   "주문 건수", "증감률"처럼 자연스러운 한국어 용어로 바꿔서 쓰세요.
9. 값이 null이거나 비어 있으면 "null"이라고 쓰지 말고 "아직 없습니다",
   "해당 상품이 없습니다"처럼 자연스러운 한국어로 표현하세요.
```

권장 config:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.2,
  "max_tokens": 2000,
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
  `seller_daily_snapshot_with_comparison(org_id, date)`. `commerce_events`
  원장을 그 판매자의 `org_id`로 필터링해서 조회수(`PRODUCT_VIEWED`)·판매·환불을
  상품별로 집계하고, `variants.stock`을 조인해 현재 재고까지 반환하는
  `seller_daily_snapshot()`에 더해, 전날 매출·주문수 집계(`previous_day`/
  `day_over_day_change`)와 이번 달 vs 지난달 비교(`seller_revenue_summary_with_comparison()`
  결과를 그대로 담은 `month_to_date`)까지 한 호출에 다 묶어서 반환한다 — 일일
  리포트·판매자 콘솔·Discord `/일일리포트`가 전부 이 함수 하나만 호출한다.
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

v2에서 규칙 6·7을 추가했다 — v1은 "하이라이트... 그대로 인용하세요"라는
문구를 모델이 JSON을 문자 그대로 베끼라는 뜻으로 오해해서, 판매자 콘솔에
`gross_revenue`/`order_count` 같은 필드명과 `(null)`이 그대로 노출되는
문제가 있었다. v2는 이 문구를 "자연스러운 한국어 문장으로 풀어서 전달"로
바꾸고, JSON 문법·null 노출을 명시적으로 금지했다. 같은 김에 다른
페르소나들과 일관되게 `reasoning: {"effort": "none"}`도 추가했다(v1에는
빠져 있었음).

v3에서 전날 대비·이번 달 vs 지난달 매출 비교 서술을 추가했다 —
`day_comparison_json`/`month_comparison_json` 변수와 규칙 3을 새로 넣고,
비교 문구가 늘어난 만큼 `max_tokens`를 1800에서 2000으로 올렸다. 증감률
계산은 여기서도 AI가 아니라 `analytics.py`의 `_percent_change()`(기준값이
0이면 `None`을 반환해 임의 수치를 만들지 않음)가 전담한다.

v4에서는 "이번 달 vs 지난달" 비교의 함정을 막는 규칙 4를 추가했다 — 이번
달이 아직 다 지나지 않았으면(예: 17일차) 항상 꽉 찬 지난달 전체 누적보다
낮게 나오는 게 당연한데, 이를 그대로 "매출 감소"라고 서술하면 오해를 부른다.
`seller_revenue_summary_with_comparison()`이 `period_in_progress`/
`days_elapsed`를 코드로 직접 계산해 같이 내려주고(날짜 계산을 AI에게 맡기지
않음), AI는 이 값을 보고 맥락을 덧붙이기만 한다.
