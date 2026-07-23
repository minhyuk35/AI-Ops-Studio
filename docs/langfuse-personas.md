# Langfuse prompt personas

AI Ops Studio의 MVP는 호출 목적이 다른 네 개의 페르소나를 사용합니다. 하나의 긴
프롬프트에 모든 책임을 넣지 않고, 입력 데이터·출력 형식·평가 기준이 다른 작업을
별도 prompt name으로 관리합니다.

| Prompt name | 책임 | 입력 | 출력 | 구현 상태 |
| --- | --- | --- | --- | --- |
| `customer-support-answer` | 고객 문의 답변 | 질문, 주문, 정책 | 고객용 한국어 답변 | 구현 |
| `support-triage` | 문의 분류·위험 판단 | 질문, 메타데이터 | 구조화된 분류 결과 | 예정 |
| `commerce-insight` | 집계 수치 해석 | 계산 완료 스냅샷 | 변화·이상치·운영 제안 | 예정 |
| `commerce-monthly-report` | 월간 보고서 편집 | 지표와 insight | 대시보드·Discord용 보고서 | 예정 |

공통 문구는 호출 가능한 페르소나로 세지 않고 Langfuse Prompt Composability로
재사용합니다.

- `_shared-brand-voice`: 말투와 브랜드 보이스
- `_shared-safety-policy`: 추측 금지, 개인정보, 상담원 이관 원칙
- `_shared-financial-truth`: AI 계산 금지, 누락 비용 고지, 인과관계 단정 금지

## Prompt name, label, config

- `name`: 어떤 작업/페르소나를 가져올지 식별합니다.
- `label`: 해당 name의 어떤 버전을 실행할지 선택합니다. 앱은 `production`을 사용합니다.
- `config`: 선택된 프롬프트 버전과 함께 배포되는 런타임 JSON입니다.
- `session_id`: 여러 고객 대화 trace를 같은 세션으로 묶습니다. 프롬프트를 중첩하는
  기능은 아닙니다.
- Prompt Composability: 프롬프트 안에서 공통 prompt를 참조해 조합하는 기능입니다.

## Config templates

문의 답변:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.2,
  "max_tokens": 700,
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

문의 분류:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0,
  "max_tokens": 300,
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

커머스 인사이트:

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

월간 리포트:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.3,
  "max_tokens": 1800,
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

모델을 바꿀 때는 새 prompt version을 만들고 검증 후 `production` 라벨을 옮깁니다.
`provider.data_collection = "deny"`는 데이터 저장을 허용하지 않는 제공자 경로만
사용하도록 제한합니다. OpenRouter의 provider fallback은 유지합니다.

코드는 `prompt.config`의 allowlist 파라미터만 OpenRouter에 전달합니다. API Key,
Base URL, Webhook URL 같은 비밀값은 config에 저장하지 않습니다.
