# Langfuse prompt personas

AI Ops Studio의 MVP는 호출 목적이 다른 다섯 개의 페르소나를 사용합니다. 하나의 긴
프롬프트에 모든 책임을 넣지 않고, 입력 데이터·출력 형식·평가 기준이 다른 작업을
별도 prompt name으로 관리합니다.

| Prompt name | 책임 | 입력 | 출력 | 구현 상태 |
| --- | --- | --- | --- | --- |
| `customer-support-answer` | 고객 문의 답변 | 질문, 주문, 정책 | 고객용 한국어 답변 | 구현 |
| `support-triage` | 문의 분류·위험 판단 | 질문 | `{category, risk, requires_human, reason}` JSON | 구현 |
| `commerce-insight` | 집계 수치 해석 | 계산 완료 스냅샷 | 변화·이상치·운영 제안 | 구현 |
| `commerce-monthly-report` | 월간 보고서 편집 | 지표와 insight | 대시보드·Discord용 보고서 | 구현 |
| `daily-seller-report` | 판매자별 일일 스냅샷 해석·재입고 제안 | 조회·판매·환불·재고 스냅샷 | 판매자 콘솔·Discord용 리포트 | 구현 |

앞의 네 개는 관리자(플랫폼 전체)용이고, `daily-seller-report`만 유일하게
**판매자 1명당 1개씩** 매일 실행된다 — 판매자 콘솔에 로그인하면 보이는
"오늘의 대시보드"와 자정마다 자동으로 나가는 Discord 리포트가 같은 코드를
공유한다. 자세한 내용은 `docs/prompts/daily-seller-report.md` 참고.

다섯 페르소나 모두 `services/core-api/app/services/personas.py`에 오프라인
fallback 텍스트·config가 있어서, Langfuse에 아직 프롬프트를 만들지 않았거나
Langfuse가 죽어 있어도 앱은 fallback으로 계속 동작합니다. 다만 fallback은
"장애 대비용"일 뿐이고, 실제로 운영·튜닝하는 프롬프트는 아래 가이드대로
Langfuse 콘솔에 등록한 버전입니다.

## Langfuse 콘솔에서 새 페르소나를 등록하는 법

문의 답변(`customer-support-answer`)은 이미 등록돼 있는 것과 동일한 방식으로,
나머지 세 개도 각각 **별도의 prompt name**으로 등록합니다. 하나의 프롬프트에
여러 책임을 몰아넣지 않는 것이 핵심입니다 — 호출 목적이 다르면 name도 달라야
버전 관리·A/B 테스트·트레이스 검색이 각자 독립적으로 됩니다.

1. Langfuse 콘솔 → **Prompts** → **New prompt**.
2. **Name**: 아래 표의 값을 정확히 입력합니다. 코드가 `.env`의
   `LANGFUSE_*_PROMPT_NAME` 값으로 이 name을 조회하므로 오타가 있으면
   조용히 fallback으로 떨어집니다.
   - `support-triage`
   - `commerce-insight`
   - `commerce-monthly-report`
   - `daily-seller-report`
3. **Type**: `Text` (Chat이 아님 — 코드가 `type="text"`로 조회합니다).
4. **Prompt**: `docs/prompts/<name>.md`에 있는 코드 블록을 그대로 붙여넣습니다.
   `{{question}}`, `{{period}}`처럼 이중 중괄호로 된 변수 이름은 코드가
   `prompt.compile(**variables)`에 넘기는 키와 정확히 일치해야 합니다
   (docs/prompts/*.md에 각 변수 이름이 적혀 있습니다).
5. **Config**: 같은 문서의 JSON을 그대로 붙여넣습니다. `model`을 바꾸면
   재배포 없이 모델이 바뀝니다.
6. **Label**: 저장할 때 `production`을 붙입니다. 앱은
   `LANGFUSE_PROMPT_LABEL=production`으로 조회하므로, label이 없는 버전은
   절대 실행되지 않습니다(안전한 초안 상태로 남습니다).
7. 저장 후 core-api를 재시작하지 않아도 됩니다 — 다음 호출부터
   `LANGFUSE_PROMPT_CACHE_TTL_SECONDS`(기본 300초) 이내에 새 버전이 반영됩니다.

같은 방식으로 모델이나 프롬프트 문구를 바꾸고 싶을 때는, 기존 name에
**새 버전(New version)**을 만들고 검증한 뒤 `production` 라벨을 그 버전으로
옮기면 됩니다. 이전 버전은 그대로 남아 있어서 즉시 롤백할 수 있습니다.

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

일일 판매자 리포트:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0.2,
  "max_tokens": 1400,
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
