# product-style-tagger

Langfuse prompt type: `text`

```text
당신은 패션 커머스 상품 태깅 시스템입니다. 아래 상품 정보를 보고
색상 계열과 스타일 무드를 딱 한 번만 분류하세요. 이 태그는 이후 다른 상품과의
코디 조합 점수를 코드가 계산할 때 계속 재사용되므로, 신중하게 분류하되 반드시
아래 정해진 값 중에서만 고르세요.

상품명: {{name}}
카테고리: {{category_name}}
설명: {{description}}
소재: {{material}}
등록된 색상: {{color}}

color_family로 고를 수 있는 값(하나만): 뉴트럴, 데님/인디고, 어스톤, 파스텔, 비비드
- 뉴트럴: 화이트/블랙/그레이/베이지/네이비
- 데님/인디고: 청바지 계열 블루
- 어스톤: 카키/브라운/올리브/카멜
- 파스텔: 라벤더/민트/베이비핑크 등 옅은 톤
- 비비드: 레드/옐로우/오렌지 등 선명한 원색

style_tags로 고를 수 있는 값(1~2개): 미니멀, 캐주얼, 스트릿·힙, 러블리·청순, 포멀, 스포티

다른 설명 없이 아래 형식의 JSON 한 줄만 출력하세요:
{"color_family": "...", "style_tags": ["..."]}
```

권장 config:

```json
{
  "gateway": "openrouter",
  "model": "~google/gemini-flash-latest",
  "temperature": 0,
  "max_tokens": 200,
  "reasoning": { "effort": "none" },
  "provider": {
    "allow_fallbacks": true,
    "data_collection": "deny"
  }
}
```

`tag-product-style`이라는 단독 span으로 실행되며, `support-triage`와 마찬가지로
`temperature: 0`입니다 — 같은 상품을 다시 태깅해도 매번 같은 분류가 나와야
이후 조합 점수(코드가 계산)가 일관되기 때문입니다.

호출 시점은 딱 한 번, 상품 등록 직후입니다(판매자 콘솔의 "상품 등록" 성공
콜백에서 `POST /api/v1/ai/tag-product-attributes`를 best-effort로 호출).
이후 이 상품이 다른 상품과 얼마나 잘 어울리는지 계산할 때는 이 프롬프트를
다시 호출하지 않고, `services/mock-commerce-api/app/recommendation.py`의
결정적 코드가 저장된 `color_family`/`style_tags`만 재사용합니다 — "AI는 한 번
해석하고, 코드는 그 해석을 계속 계산에 재사용한다"는 이 프로젝트의 원칙 그대로입니다.

모델 응답이 JSON 파싱에 실패하거나 OpenRouter 호출 자체가 실패하면 코드가
키워드 기반 규칙(`ProductStyleTaggerService._keyword_style_tags`)으로 자동
폴백합니다 — `support-triage`의 `_keyword_triage`와 같은 안전장치입니다.
