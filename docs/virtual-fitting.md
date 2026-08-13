# 가상 카메라 피팅 (웹캠 실시간 착장) — 상세 문서

## 0. 질문에 대한 답: "올라간 사진을 기준으로 입어보는 방식인가?"

**네, 맞습니다.** 가상 피팅은 **상품에 등록된 대표 사진(`product.image`)을 그대로 가져와** 웹캠
영상 위에 겹칩니다. 즉 별도의 3D 모델이나 전용 착장 에셋이 아니라, **카탈로그에 올라가 있는
그 사진**을 실시간으로 추적한 몸(어깨) 위에 얹어 "입어본 것처럼" 보여주는 방식입니다.

- 판매자가 상품 이미지를 바꾸면(파일 업로드/URL) 피팅에 쓰이는 이미지도 자동으로 그 이미지가 됩니다.
- 그래서 **카테고리에 맞는 사진 = 피팅도 맞는 사진**입니다(SIGN 샘플 카탈로그도 카테고리 키워드로
  이미지를 넣은 이유).

> 한계: 지금은 상품 사진이 배경 있는 일반 사진이라 겹칠 때 배경까지 같이 올라가 조금 어색합니다.
> 배경이 투명한 착장용 PNG를 쓰면 훨씬 자연스러워집니다(로드맵 Phase 1 후속).

---

## 1. 어디서 뜨나

상품 상세 페이지의 **"📷 가상 피팅으로 입어보기"** 버튼. 어깨선 기준 오버레이라
**상의·아우터**(카테고리 slug가 `top*` / `outer*`)에서만 버튼이 나타납니다.
하의·신발·가방·주얼리는 어깨 오버레이가 맞지 않아 숨깁니다(카테고리별 배치는 Phase 2).

---

## 2. 동작 파이프라인

```
[가상 피팅 버튼]
   │  (lazy: 이때 처음 VirtualFitting 청크 + MediaPipe 로드)
   ▼
1. 포즈 모델 로드   FilesetResolver.forVisionTasks(WASM) → PoseLandmarker.createFromOptions
                    (delegate GPU 시도 → 실패 시 CPU 폴백, runningMode: "VIDEO", numPoses: 1)
2. 상품 이미지 로드  new Image(); img.src = product.image  (CORS 허용 시 스냅샷도 가능)
3. 웹캠 열기        navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } })
   ▼ (매 프레임, requestAnimationFrame 루프)
4. 프레임 그리기     캔버스를 좌우 반전(셀피)하고 video 프레임을 draw
5. 포즈 추정        landmarker.detectForVideo(video, performance.now()) → 33개 랜드마크
6. 착장 합성        어깨 두 점(11,12)으로 옷의 각도·너비 계산 → 상품 이미지를 회전·스케일해 겹침
                    (골반 23,24가 잡히면 상의 길이를 몸통 비율에 맞춤)
7. (옵션) 골격 표시   '포즈 골격' 토글 시 랜드마크 선/점을 함께 렌더
```

### 어깨 기준 배치 수식(요지)
- `shoulderDist = |R - L|` (오른쪽·왼쪽 어깨 픽셀 거리)
- `angle = atan2(R.y - L.y, R.x - L.x)` → 옷 회전각(어깨 기울기)
- `garmentWidth = shoulderDist × 2.35 × scale(사용자 슬라이더)` (옷은 어깨너비보다 넓다)
- 어깨 중점에 배치하고 `angle`만큼 회전, 목선이 어깨보다 살짝 위에 오도록 `offsetY`로 미세조정

---

## 3. 사용 기술 · 라이브러리

| 계층 | 기술 |
|------|------|
| 카메라 입력 | `navigator.mediaDevices.getUserMedia` (WebRTC), `<video>` |
| 포즈 추정 | **`@mediapipe/tasks-vision`** `PoseLandmarker` (33개 랜드마크) |
| 모델·WASM | CDN 로드 — WASM: `cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm`, 모델: `pose_landmarker_lite.task` (Google storage) |
| 렌더링 | `<canvas>` 2D + `requestAnimationFrame` |
| 코드 분할 | `React.lazy` — 버튼 누를 때만 로드(약 gzip 42KB 청크) |

> 완전 오프라인이 필요하면 위 WASM/모델 파일을 `apps/demo-store/public/` 에 받아 두고
> `VirtualFitting.tsx` 상단의 `WASM_BASE` / `MODEL_URL` 상수만 로컬 경로로 바꾸면 됩니다.

---

## 4. 조작 UI

- **의류 겹치기** 토글 — 상품 이미지 오버레이 on/off
- **포즈 골격** 토글 — 33개 랜드마크 골격 표시(Phase 0 확인용)
- **크기** 슬라이더 — 옷 너비 배율(0.7~1.6)
- **위치** 슬라이더 — 옷 상하 오프셋(−80~80px)
- **📸 사진 저장** — 현재 캔버스를 PNG로 저장(상품 이미지가 CORS 허용일 때)

---

## 5. 개인정보 · 보안

- 웹캠 영상은 **브라우저 안에서만** 처리됩니다. **서버로 전송·저장하지 않습니다.**
- 포즈 추정도 브라우저 내 추론(WASM/GPU)이라 프레임이 외부로 나가지 않습니다.
- 모달을 닫거나 페이지를 벗어나면 카메라 트랙을 즉시 정지(`track.stop()`)하고 모델을 `close()` 합니다.

---

## 6. 필요 조건(브라우저)

- **보안 컨텍스트 필수**: 웹캠은 `https://` 또는 `http://localhost` 에서만 동작합니다.
  배포(Vercel, HTTPS)와 로컬 `localhost:5174`는 OK. LAN IP(`http://192.168.x.x`)는 브라우저가 막습니다.
- 첫 실행 시 **카메라 권한 허용** 필요. 거부 시 안내 문구 표시.
- 첫 로드 시 모델·WASM을 CDN에서 받으므로 인터넷 필요.

---

## 7. 현재 한계

1. **상품 사진을 그대로 겹침** — 배경 있는 사진이면 배경까지 올라가 어색. → 투명 배경 착장 PNG 권장.
2. **어깨 기준 정면 배치** — 옆으로 돌거나 팔이 옷을 가리는 상황은 아직 반영 안 됨.
3. **카테고리별 배치 없음** — 상의/아우터에만 노출. 하의·신발은 다른 부위 배치가 필요(Phase 2~).
4. **인물 분리 없음** — 사람과 배경을 분리하지 않아 옷이 배경 위에도 살짝 겹칠 수 있음.

---

## 8. 튜닝 포인트 (`apps/demo-store/src/VirtualFitting.tsx`)

| 값 | 위치 | 의미 |
|----|------|------|
| `2.35` | `drawGarment` `width = shoulderDist * 2.35 * scale` | 어깨너비 대비 옷 너비 배율(더 크게/작게) |
| `-height * 0.16` | `drawGarment` `top` | 목선이 어깨보다 얼마나 위로 올라갈지 |
| `0.92` | `ctx.globalAlpha` | 옷 오버레이 불투명도 |
| `WASM_BASE`, `MODEL_URL` | 파일 상단 | 모델·WASM 소스(자체호스팅 시 교체) |

---

## 9. 단계별 로드맵

| 단계 | 내용 | 상태 |
|------|------|------|
| Phase 0 | 웹캠 + 실시간 포즈 골격 추적 | ✅ 구현 |
| Phase 1 | 어깨 기준 2D 착장(상품 이미지 오버레이) | ✅ 구현 |
| Phase 1.5 | 투명 배경 착장 이미지 파이프라인 | 로드맵 |
| Phase 2 | 인물 세그멘테이션 + 사이즈 프로필 연동 + 카테고리별 배치(하의/신발) | 로드맵 |
| Phase 3 | 앞/뒤 레이어링 · 측면 포즈 | 로드맵 |
| Phase 4 | 3D 메쉬 옷감 시뮬레이션 | 로드맵 |

---

## 10. 파일 구성

| 파일 | 역할 |
|------|------|
| `apps/demo-store/src/VirtualFitting.tsx` | 피팅 모달 전체(웹캠·포즈·오버레이·컨트롤·정리) |
| `apps/demo-store/src/App.tsx` (`ProductPage`) | "가상 피팅" 버튼(상의/아우터만) + lazy 로드 |
| `apps/demo-store/src/styles.css` (`.vf-*`, `.fit-button`) | 모달·버튼 스타일(모바일 전체화면 포함) |

---

## 11. 테스트 방법

1. `pnpm --filter @ai-ops/demo-store dev` (또는 배포 사이트 접속).
2. **상의/아우터** 상품 상세로 이동(SIGN 샘플 카탈로그의 맨투맨·셔츠·티셔츠·니트·자켓·코트·후드집업).
3. "📷 가상 피팅으로 입어보기" → 카메라 허용 → 상반신이 보이게 서기.
4. 크기·위치 슬라이더로 맞추고, 필요하면 '포즈 골격'으로 추적 상태 확인, '사진 저장'으로 캡처.
