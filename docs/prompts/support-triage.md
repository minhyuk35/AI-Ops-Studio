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
- requires_human: 이 문의에 상담원(사람)이 반드시 개입해야 하면 true, AI 답변만으로
  충분히 해결 가능하면 false. risk가 HIGH이면 반드시 true. 감사 인사·단순 인사말·
  일반적인 안내로 충분한 통상적인 질문(예: "감사합니다", "언제 배송되나요?")은
  특별한 사유가 없는 한 false로 하세요.

다른 설명 없이 아래 형식의 JSON 한 줄만 출력하세요:
{"category": "...", "risk": "...", "requires_human": false, "reason": "..."}
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

## v2 변경 사항 (2026-08-20)

v1의 출력 예시가 `"requires_human": true`였는데, 이 예시 자체가 모델이 실제
문의 내용과 무관하게 true를 더 자주 출력하도록 편향시킬 수 있다는 문제가
있었다 — 배송 문의처럼 risk가 LOW인데도 AI가 이미 답변을 마쳤음에도
requires_human을 true로 반환해, `_notify_discord`가 (구버전 로직에서) risk와
무관하게 무조건 "🚨 상담원 이관 필요"로 알림을 보내는 문제로 이어졌다. v2는
예시를 `false`로 바꾸고, requires_human을 언제 false로 둬야 하는지(감사 인사,
단순 안내로 충분한 통상적 질문 등) 명시적인 규칙을 추가했다.
