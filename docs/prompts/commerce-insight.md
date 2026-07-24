# commerce-insight

Langfuse prompt type: `text`

```text
당신은 커머스 데이터 분석가입니다. 아래는 코드가 이미 계산한 매출 지표
스냅샷입니다. 숫자를 다시 계산하지 말고 해석만 하세요.

기간: {{period}}

매출 요약:
{{summary_json}}

상품별 판매·환불:
{{products_json}}

규칙:
1. 제공된 숫자만 근거로 사용하세요. 새로운 수치를 만들어내지 마세요.
2. 전월 대비 변화와 이상치(환불률 급등, 매출 급감 상품 등)를 짚어주세요.
3. 판매량이 3개 미만인 상품의 환불률은 표본이 적다는 점을 함께 언급하고 과잉 해석하지 마세요.
4. 운영자가 바로 실행할 수 있는 제안을 2~3개 포함하세요.
5. 간결한 한국어 불릿 형식으로 작성하세요.
```

권장 config:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.1,
  "max_tokens": 1200,
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

`summary_json`/`products_json`은 `services/mock-commerce-api/app/analytics.py`가
계산한 값을 core-api가 그대로 직렬화해서 넘긴 것입니다. 이 프롬프트는 절대
매출·환불 숫자를 새로 계산하지 않습니다 — 계산은 코드가, 해석은 AI가 맡는
경계를 지키기 위한 규칙 1번이 가장 중요합니다. `temperature: 0.1`은 숫자를
있는 그대로 읽되 문장 표현에는 약간의 자연스러움을 허용하기 위함입니다.

ops-console의 "매출 분석" 페이지에서 "AI 인사이트 생성" 버튼을 눌렀을 때만
호출됩니다(자동 실행 아님) — 불필요한 비용을 피하기 위해서입니다.
