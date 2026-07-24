"""판매자 플랜 → Discord 카테고리/채널/페르소나 매핑의 단일 진실 공급원.

봇(services/discord-bot)은 이 매핑을 직접 들고 있지 않고 ``GET
/internal/discord/org`` 응답의 ``channels`` 배열로 받아 그대로 카테고리·채널·
웹훅을 만든다. 매핑이 오직 이 파일 한 곳에만 있으므로 봇과 커머스 API가
플랜별 채널 구성에서 절대 어긋나지 않는다.

각 채널의 ``persona``는 Langfuse prompt name이다. 봇은 채널과 웹훅만
"판까지" 깔아 두고, 실제 AI 리포트 생성·발신은 판매자 노트북에서 이 웹훅
URL로 진행한다(요구사항: "AI 관련은 내 노트북에서"). ``persona``가 None인
채널(봇-명령)은 사람이 슬래시 명령을 입력하는 용도라 페르소나가 없다.

관리자 전용 페르소나(platform-daily-traffic, seller-market-share-report)는
판매자에게 노출되면 안 되므로 어떤 판매자 플랜에도 포함하지 않는다.
"""

# 봇이 생성/삭제를 관리하는 카테고리 이름. /생성은 이 카테고리와 그 하위
# 채널만 초기화·재생성하므로, 판매자가 서버에 따로 만든 다른 채널은 건드리지
# 않는다(전체 초기화는 /생성 전체초기화:true 옵션에서만).
CATEGORY_NAME = "AI OPS STUDIO"

# channel_key -> 채널 메타. name은 디스코드 채널명, persona는 Langfuse prompt
# name(노트북 AI가 이 채널 웹훅으로 보낼 때 사용할 페르소나), topic은 채널 설명.
CHANNEL_SPECS: dict[str, dict[str, str | None]] = {
    "commands": {
        "name": "봇-명령",
        "persona": None,
        "topic": "슬래시 명령(/수익 · /조회수 · /일일리포트 · /재고)으로 지표를 즉시 조회",
    },
    "daily": {
        "name": "일일-리포트",
        "persona": "daily-seller-report",
        "topic": "매일 오늘의 조회·판매·환불·재고를 요약한 판매자 전담 리포트",
    },
    "support": {
        "name": "문의-이관",
        "persona": "customer-support-answer",
        "topic": "AI가 자동 응대하고, 민감/고위험 문의는 이 채널로 사람에게 이관",
    },
    "monthly": {
        "name": "월간-리포트",
        "persona": "commerce-monthly-report",
        "topic": "월 단위 매출·환불·추세를 편집한 월간 운영 리포트",
    },
    "insight": {
        "name": "매출-인사이트",
        "persona": "commerce-insight",
        "topic": "상품별 판매·환불 이상치와 실행 제안을 담은 심층 인사이트",
    },
}

# 플랜 → 포함 채널(순서 = 생성 순서). 상위 플랜은 하위 플랜을 포함한다.
PLAN_CHANNELS: dict[str, list[str]] = {
    "FREE": ["commands", "daily"],
    "BASIC": ["commands", "daily", "support"],
    "PRO": ["commands", "daily", "support", "monthly"],
    "BUSINESS": ["commands", "daily", "support", "monthly", "insight"],
}


def normalize_plan(plan: str | None) -> str:
    candidate = (plan or "FREE").upper()
    return candidate if candidate in PLAN_CHANNELS else "FREE"


def channels_for_plan(plan: str | None) -> list[dict[str, str | None]]:
    """플랜에 해당하는 채널 스펙 목록(생성 순서대로)."""
    keys = PLAN_CHANNELS[normalize_plan(plan)]
    return [{"channel_key": key, **CHANNEL_SPECS[key]} for key in keys]
