"""One-time (or after changing a command's name/options) script: registers
the slash commands globally via Discord's REST API.

Registering *what commands exist* is a separate Discord API from
*handling* an interaction (interactions_app.py) -- the HTTP Interactions
endpoint never registers commands on its own, so this has to be run
manually whenever the command list changes. Global registration can take
up to an hour to propagate to all servers.

Usage:
    python register_commands.py
"""

import os
import sys

import httpx

API_BASE = "https://discord.com/api/v10"
STRING_OPTION = 3
BOOLEAN_OPTION = 5

COMMANDS = [
    {
        "name": "실행",
        "description": "연동 코드로 상점을 연결하고, 플랜에 맞는 채널·웹훅을 (재)생성합니다.",
        "options": [
            {
                "name": "코드",
                "description": "아직 연동 전이라면 판매자 콘솔에서 발급받은 코드",
                "type": STRING_OPTION,
                "required": False,
            },
            {
                "name": "전체초기화",
                "description": "봇 카테고리 외 다른 채널까지 모두 삭제 후 재생성(주의)",
                "type": BOOLEAN_OPTION,
                "required": False,
            },
        ],
    },
    {
        "name": "수익",
        "description": "이 상점의 월 매출 요약을 조회합니다.",
        "options": [
            {
                "name": "기간",
                "description": "YYYY-MM (비우면 이번 달)",
                "type": STRING_OPTION,
                "required": False,
            }
        ],
    },
    {
        "name": "조회수",
        "description": "오늘(또는 지정일) 상품 조회수를 조회합니다.",
        "options": [
            {
                "name": "날짜",
                "description": "YYYY-MM-DD (비우면 오늘)",
                "type": STRING_OPTION,
                "required": False,
            }
        ],
    },
    {
        "name": "일일리포트",
        "description": "오늘의 조회·판매·환불·재고 스냅샷.",
        "options": [
            {
                "name": "날짜",
                "description": "YYYY-MM-DD (비우면 오늘)",
                "type": STRING_OPTION,
                "required": False,
            }
        ],
    },
    {
        "name": "재고",
        "description": "품절·재고 임박 상품을 조회합니다.",
        "options": [],
    },
    {
        "name": "연동상태",
        "description": "연동 여부와 생성된 채널을 확인합니다.",
        "options": [],
    },
]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root_env = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(root_env)


def main() -> None:
    _load_env()
    application_id = os.getenv("DISCORD_APPLICATION_ID", "").strip()
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not application_id or not bot_token:
        sys.exit("DISCORD_APPLICATION_ID / DISCORD_BOT_TOKEN이 .env에 필요합니다.")

    response = httpx.put(
        f"{API_BASE}/applications/{application_id}/commands",
        headers={"Authorization": f"Bot {bot_token}"},
        json=COMMANDS,
        timeout=30,
    )
    if response.status_code >= 400:
        sys.exit(f"등록 실패 ({response.status_code}): {response.text}")

    registered = response.json()
    print(f"{len(registered)}개 전역 명령어 등록 완료 (반영에 최대 1시간 소요):")
    for command in registered:
        print(f"  /{command['name']}")


if __name__ == "__main__":
    main()
