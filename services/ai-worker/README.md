# AI Worker

비동기 문의 처리, 재시도, 실패 큐를 추가할 위치입니다.

MVP 초기에는 Core API의 threadpool에서 OpenRouter를 호출합니다. 이후 Redis 기반 작업 큐로 분리할 때 다음 작업을 담당합니다.

- 문의 의도 분류
- Commerce API 조회
- 정책 검색/RAG
- Langfuse runtime config에 따른 OpenRouter 답변 생성
- 신뢰도 및 위험 규칙 검사
- WebSocket 이벤트 발행
