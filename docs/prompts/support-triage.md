# support-triage

Langfuse prompt type: `text`

```text
당신은 쇼핑몰 고객문의 분류 시스템입니다.
아래 문의를 읽고 반드시 JSON으로만 답하세요.

문의:
{{question}}

분류 기준:
- category: DELIVERY(배송) | CANCEL(취소) | REFUND(반품·환불) | OTHER(기타) 중 하나
- risk: LOW | MEDIUM | HIGH — 분쟁, 소송, 신고, 고액 환불, 개인정보 유출이 언급되면 HIGH
- requires_human: risk가 HIGH이면 반드시 true

다른 설명 없이 아래 형식의 JSON 한 줄만 출력하세요:
{"category": "...", "risk": "...", "requires_human": true, "reason": "..."}
```

권장 config:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0,
  "max_tokens": 300,
  "reasoning": { "effort": "none" },
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

`answer-customer-inquiry` 트레이스 안에서 `classify-inquiry`라는 별도 span으로
실행되며, `generate-support-reply`(customer-support-answe     r)보다 먼저 호출됩니다.
`temperature: 0`인 이유는 분류값이 매번 일관돼야 하기 때문입니다 — 답변 생성용
프롬프트와 달리 창의성이 필요 없습니다.

모델 응답이 JSON 파싱에 실패하거나 OpenRouter 호출 자체가 실패하면 코드가
키워드 기반 규칙(`OpenRouterSupportService._keyword_triage`)으로 자동 폴백합니다.
`requires_human` 최종 판단은 이 프롬프트의 결과와, 코드에 하드코딩된 안전 키워드
검사(`HUMAN_HANDOFF_KEYWORDS`) 중 하나라도 true면 상담원에게 이관되도록 OR로
결합됩니다 — 이관 여부를 LLM 하나에만 맡기지 않기 위한 안전장치입니다.
