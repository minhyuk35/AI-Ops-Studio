# PostgreSQL 전환

기본값은 항상 SQLite다. `DATABASE_URL`을 비워두면 core-api와
mock-commerce-api 모두 지금까지와 동일하게 `data/commerce.db`,
`data/support.db` SQLite 파일을 그대로 쓴다 — 로컬 개발과 테스트 스위트
(`pytest`, 61개 전부 통과)는 이 경로로만 검증되어 있다.

`DATABASE_URL`을 `postgres://` 또는 `postgresql://`로 시작하는 값으로
채우면 두 서비스 모두 [psycopg](https://www.psycopg.org/psycopg3/)로 그
Postgres에 연결한다. **이 경로는 코드만 작성된 상태이고, 실제 Postgres
인스턴스에 대해 실행/검증된 적이 없다** — 이 환경에는 로컬 Postgres나
Docker가 없어서 라이브 테스트가 불가능했다. 운영 전환 전에는 반드시 Neon
같은 무료 인스턴스 하나를 만들어 아래 순서로 직접 검증할 것.

## 왜 Supabase가 아니라 Neon인가

Supabase는 명시적으로 제외 — 이미 무료 Postgres 호스팅 중 Supabase를 뺀
대안을 요청받았다.

- **[Neon](https://neon.tech)**: 순수 Postgres 서버리스. 무료 티어가
  영구적이고(카드 없이 가입 가능), 사용하지 않을 때 컴퓨트가 0으로
  줄어드는 scale-to-zero라 무료 한도 안에서 오래 유지하기 쉽다. 표준
  `postgres://user:pass@host/db?sslmode=require` 접속 문자열을 그대로
  주므로 이 프로젝트의 `DATABASE_URL`에 바로 넣을 수 있다.
- **[CockroachDB Serverless](https://www.cockroachlabs.com/product/cockroachdb-serverless/)**:
  Postgres 와이어 프로토콜 호환. 무료 티어 있음. 분산 DB라 지연시간이
  Neon보다 살짝 더 튈 수 있지만 완전한 대안.
- Railway/Render의 무료 Postgres는 최근 계속 축소되는 추세라(카드 등록
  요구, 만료 기한 등) 1순위로 추천하지 않는다.

## Neon으로 실제 전환하는 순서

1. https://neon.tech 가입 → 새 프로젝트 생성 (리전은 아무 곳이나, 지연시간
   신경쓰면 서울과 가까운 리전).
2. 콘솔의 **Connection string**을 복사한다. `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`
   형태다.
3. 루트 `.env`의 `DATABASE_URL`에 그대로 붙여넣는다.
4. `pip install -r requirements.txt`로 `psycopg[binary,pool]`을 설치한다
   (이미 requirements.txt에 추가되어 있음).
5. core-api와 mock-commerce-api를 각각 재시작한다. 두 서비스 모두 부팅 시
   `initialize_database()`/`OpsStore.initialize()`/`InquiryStore.initialize()`
   가 스키마 생성과 시드 데이터 삽입을 자동으로 시도한다.
6. 아래 "알려진 위험" 항목을 하나씩 눈으로 확인한다. 특히 시드 데이터가
   중복 없이 들어가는지(`ON CONFLICT DO NOTHING`), 판매자 콘솔/관리자
   콘솔의 숫자가 SQLite로 돌렸을 때와 같은지 비교한다.
7. 문제 없으면 `pytest`를 `DATABASE_URL`을 채운 채로 한 번 더 돌려서
   회귀가 없는지 확인한다 (현재는 SQLite로만 통과가 확인된 상태).

## 무엇을 바꿨는지

- `services/mock-commerce-api/app/db_compat.py`,
  `services/core-api/app/services/db_compat.py`: 각 서비스에 독립적으로
  존재하는 동일한 얇은 호환 레이어. `is_postgres()`가 `DATABASE_URL`
  스킴을 보고 분기하고, `PostgresConnection`이 `sqlite3.Connection`과
  같은 `execute`/`executemany`/`executescript`/`commit`/`rollback`/`close`
  인터페이스를 psycopg 위에 흉내낸다.
- SQL 재작성은 텍스트 치환으로만 한다 (별도 쿼리 빌더 없음):
  - `INSERT OR IGNORE INTO` → `INSERT INTO ... ON CONFLICT DO NOTHING`
    (대상 컬럼을 지정하지 않아도 두 엔진 모두 유니크 제약 충돌 시
    무시한다).
  - `LIKE` → `ILIKE` (SQLite의 기본 대소문자 무시 매칭을 Postgres에서도
    유지하기 위해).
  - 이름 있는 파라미터 `:name` → `%(name)s`, 위치 파라미터 `?` → `%s`.
  - `PRAGMA table_info(table)` (컬럼 마이그레이션용) → Postgres에서는
    `information_schema.columns` 조회로 분기.
  - `PRAGMA foreign_keys`/`journal_mode`, `BEGIN IMMEDIATE`는 SQLite
    전용이라 Postgres 경로에서는 그냥 건너뛴다 (Postgres는 외래키가
    항상 강제되고, 첫 문장 실행 시 트랜잭션이 자동 시작된다).
- 스키마(`CREATE TABLE`)는 두 엔진에서 100% 동일한 SQL을 쓴다 — 모든
  기본키가 `TEXT`(UUID 문자열)라 SQLite의 `INTEGER PRIMARY KEY`
  auto-increment 특이 케이스가 아예 없고, 컬럼 타입도 `TEXT`/`INTEGER`/
  `REAL`로 Postgres에서도 그대로 유효한 이름만 썼기 때문. 유일한 차이는
  `executescript()`가 세미콜론 기준으로 문장을 쪼개 하나씩 실행한다는
  점뿐이다 (psycopg는 SQLite처럼 한 번에 여러 문장을 실행하는 API가
  없음).

## 검증 계획 (아직 못 한 것)

- `psycopg`/`psycopg_pool`이 실제로 설치·동작하는지: 이 환경엔 없어서
  `import ast`로 문법만 확인했다. 런타임 동작은 미확인.
- 실제 Postgres에 `initialize_database()`가 처음부터 끝까지 에러 없이
  도는지 (스키마 생성 → 컬럼 마이그레이션 → 시드 삽입 → 5개 매장/60여
  상품 seed까지).
- `GROUP BY` 절 — SQLite는 관대하지만 Postgres는 SELECT 비집계 컬럼이
  전부 GROUP BY에 있어야 한다. `analytics.py`의 쿼리들은 이미 그렇게
  작성돼 있어서(과거에도 이 규칙을 지켜 작성했음) 이론상 문제 없어야
  하지만 실측 전까지는 가정일 뿐이다.
- 커넥션 풀링: 지금 구현은 요청마다 `psycopg.connect()`를 새로 여는
  구조를 그대로 따른다 (SQLite와 동일 패턴). 로컬 파일 기반 SQLite에서는
  거의 공짜지만 Postgres에서는 매 요청 TCP 핸드셰이크 비용이 붙는다.
  트래픽이 늘면 `psycopg_pool.ConnectionPool`로 바꿔야 하지만, 지금은
  요청 수가 적은 데모/포트폴리오 규모라 우선순위를 낮췄다.
- Vercel 배포와의 조합: 서버리스 함수는 요청마다 콜드 스타트될 수 있어
  매 요청 새 커넥션을 여는 지금 구조와도 궁합이 맞다(반대로 커넥션
  풀을 코드가 들고 있으면 서버리스에서는 오히려 손해). 다만 core-api의
  백그라운드 스케줄러(`app/services/scheduler.py`)는 Vercel의 요청 단위
  실행 모델과 무관하게 상시 실행 프로세스가 필요하므로 Render/Railway/
  Fly.io 같은 상시 구동 호스트에 올려야 한다 — 이건 DB 종류와 무관하게
  이미 있던 제약이다.
