"""SIGN 매장 샘플 카탈로그 시드 — 모든 리프(말단) 카테고리마다 상품 10개씩.

배포(Neon/Postgres)와 로컬(SQLite) 양쪽에서 돌아간다(app.db 호환 레이어 사용).
멱등: 상품/옵션 id가 결정론적이라 여러 번 돌려도 중복이 안 생긴다.

이미지는 카테고리별 키워드로 LoremFlickr에서 가져온다(상품마다 고유 lock →
서로 다른, 카테고리에 맞는 사진). 프로덕트 상세의 "가상 피팅"도 이 이미지를
그대로 겹쳐서 입어보므로, 카테고리에 맞는 이미지 = 피팅도 맞는 이미지.

실행:
  # 배포 DB(Neon)에 넣기
  $env:PYTHONPATH="services/mock-commerce-api"
  $env:DATABASE_URL="postgresql://.../neondb?sslmode=require"
  python scripts/seed_sign_catalog.py
  # 로컬 SQLite에 넣기(개발): DATABASE_URL 을 비우고 실행
"""
# ruff: noqa: E501  (카테고리 설정 dict는 한 줄에 한 카테고리로 두는 게 읽기 쉬움)

import os
import sys
import zlib
from pathlib import Path

# services/mock-commerce-api 를 import 경로에 올린다(스크립트 단독 실행용).
_SVC = Path(__file__).resolve().parents[1] / "services" / "mock-commerce-api"
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.db import transaction, utc_now  # noqa: E402

PER_CATEGORY = 10

# 사이즈 세트(카테고리 성격별)
SIZES_TOP = ["S", "M", "L", "XL"]
SIZES_BOTTOM = ["28", "30", "32", "34"]
SIZES_SHOES = ["250", "260", "270", "280"]
SIZES_FREE = ["FREE"]
SIZES_BELT = ["S", "M", "L"]

APPAREL_MODS = ["오버핏", "베이직", "슬림", "와이드", "빈티지", "미니멀", "클래식", "릴렉스드", "스탠다드", "데일리"]
ACC_MODS = ["미니멀", "클래식", "베이직", "빈티지", "레더", "캔버스", "메탈", "데일리", "라운드", "스퀘어"]
SHOE_MODS = ["미니멀", "클래식", "레트로", "청키", "데일리", "레더", "캔버스", "코트", "러너", "슬립온"]

COLORS = ["블랙", "화이트", "그레이", "네이비", "베이지", "크림", "카키", "브라운", "블루", "차콜"]
COLOR_FAMILY = {
    "블랙": "뉴트럴", "화이트": "뉴트럴", "그레이": "뉴트럴", "크림": "뉴트럴",
    "베이지": "뉴트럴", "차콜": "뉴트럴", "네이비": "블루", "블루": "블루",
    "카키": "카키", "브라운": "브라운",
}

# 리프 카테고리 slug -> 설정
CATALOG = {
    "top-sweatshirt": dict(noun="맨투맨", kw="sweatshirt", sizes=SIZES_TOP, mods=APPAREL_MODS,
                           price=(35000, 69000), material="코튼 100%", care="찬물 단독 세탁",
                           tags="캐주얼,데일리"),
    "top-shirt": dict(noun="셔츠", kw="shirt", sizes=SIZES_TOP, mods=APPAREL_MODS,
                      price=(39000, 89000), material="코튼 100%", care="30도 이하 세탁",
                      tags="캐주얼,클래식"),
    "top-tee": dict(noun="티셔츠", kw="tshirt", sizes=SIZES_TOP, mods=APPAREL_MODS,
                    price=(19000, 45000), material="코튼 100%", care="찬물 세탁, 뒤집어 건조",
                    tags="캐주얼,데일리"),
    "top-knit": dict(noun="니트", kw="sweater,knit", sizes=SIZES_TOP, mods=APPAREL_MODS,
                     price=(45000, 98000), material="울 50%, 아크릴 50%", care="드라이클리닝 권장",
                     tags="미니멀,클래식"),
    "bottom-denim": dict(noun="데님팬츠", kw="jeans,denim", sizes=SIZES_BOTTOM, mods=APPAREL_MODS,
                         price=(45000, 98000), material="코튼 98%, 폴리우레탄 2%", care="뒤집어 단독 세탁",
                         tags="캐주얼,데일리"),
    "bottom-slacks": dict(noun="슬랙스", kw="trousers,slacks", sizes=SIZES_BOTTOM, mods=APPAREL_MODS,
                          price=(49000, 89000), material="폴리에스터 70%, 레이온 30%", care="드라이클리닝",
                          tags="미니멀,클래식"),
    "bottom-cargo": dict(noun="카고팬츠", kw="cargo,trousers", sizes=SIZES_BOTTOM, mods=APPAREL_MODS,
                         price=(49000, 89000), material="코튼 100%", care="30도 이하 세탁",
                         tags="스트릿,캐주얼"),
    "bottom-shorts": dict(noun="숏팬츠", kw="shorts", sizes=SIZES_BOTTOM, mods=APPAREL_MODS,
                          price=(29000, 59000), material="코튼 100%", care="찬물 세탁",
                          tags="캐주얼,데일리"),
    "outer-jacket": dict(noun="자켓", kw="jacket", sizes=SIZES_TOP, mods=APPAREL_MODS,
                         price=(89000, 199000), material="폴리에스터 100%", care="드라이클리닝",
                         tags="캐주얼,클래식"),
    "outer-coat": dict(noun="코트", kw="coat", sizes=SIZES_TOP, mods=APPAREL_MODS,
                       price=(129000, 259000), material="울 70%, 폴리 30%", care="드라이클리닝",
                       tags="미니멀,클래식"),
    "outer-hoodzip": dict(noun="후드집업", kw="hoodie", sizes=SIZES_TOP, mods=APPAREL_MODS,
                          price=(49000, 89000), material="코튼 80%, 폴리 20%", care="찬물 세탁",
                          tags="스트릿,캐주얼"),
    "shoes": dict(noun="스니커즈", kw="sneakers,shoes", sizes=SIZES_SHOES, mods=SHOE_MODS,
                  price=(59000, 159000), material="천연가죽/러버 아웃솔", care="전용 클리너 사용",
                  tags="스트릿,데일리"),
    "accessories-bag": dict(noun="백", kw="bag,handbag", sizes=SIZES_FREE, mods=ACC_MODS,
                            price=(29000, 129000), material="소가죽/캔버스", care="오염 부위만 닦기",
                            tags="미니멀,데일리"),
    "accessories-belt": dict(noun="벨트", kw="belt,leather", sizes=SIZES_BELT, mods=ACC_MODS,
                             price=(19000, 49000), material="소가죽 100%", care="물기 피하기",
                             tags="미니멀,클래식"),
    "accessories-cap": dict(noun="볼캡", kw="cap,hat", sizes=SIZES_FREE, mods=ACC_MODS,
                            price=(19000, 39000), material="코튼 100%", care="손세탁 후 그늘 건조",
                            tags="캐주얼,데일리"),
    "accessories-jewelry": dict(noun="주얼리", kw="jewelry,necklace", sizes=SIZES_FREE, mods=ACC_MODS,
                                price=(15000, 89000), material="925 실버/서지컬 스틸", care="땀·물 접촉 피하기",
                                tags="미니멀,데일리"),
}


def _image(kw: str, lock: int, w: int = 600, h: int = 750) -> str:
    return f"https://loremflickr.com/{w}/{h}/{kw}?lock={lock}"


def _price(low: int, high: int, i: int) -> int:
    span = high - low
    raw = low + round(span * (i / (PER_CATEGORY - 1))) if PER_CATEGORY > 1 else low
    return int(round(raw / 1000) * 1000)


def _ensure_sign_org(connection) -> str:
    row = connection.execute("SELECT id FROM organizations WHERE name = ?", ("SIGN",)).fetchone()
    if row is not None:
        return row["id"]
    # 로컬(SQLite) 등 SIGN 이 없는 환경에서는 만들어 준다.
    from app.auth import hash_password
    now = utc_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
        VALUES(?,?,?,?,?,0,?)
        """,
        ("cus_sign", "sign@sign.store", "SIGN", "010-0000-0001", hash_password("sign1234"), now),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO organizations(
            id, owner_customer_id, name, category, commission_rate, status, plan, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        ("org_sign", "cus_sign", "SIGN", "패션", 0.08, "ACTIVE", "BUSINESS", now),
    )
    return "org_sign"


def _leaf_categories(connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT c.id, c.slug, c.name FROM categories c
        WHERE NOT EXISTS (SELECT 1 FROM categories ch WHERE ch.parent_id = c.id)
        ORDER BY c.sort_order
        """
    ).fetchall()
    return [dict(r) for r in rows]


def seed() -> None:
    inserted_products = 0
    inserted_variants = 0
    with transaction() as connection:
        org_id = _ensure_sign_org(connection)
        leaves = _leaf_categories(connection)
        now = utc_now()
        for cat in leaves:
            conf = CATALOG.get(cat["slug"])
            if conf is None:
                print(f"  (설정 없는 리프 카테고리 건너뜀: {cat['slug']})")
                continue
            key = cat["slug"].replace("-", "_")
            for i in range(PER_CATEGORY):
                mod = conf["mods"][i % len(conf["mods"])]
                color = COLORS[i % len(COLORS)]
                name = f"SIGN {mod} {conf['noun']} {i + 1:02d}"
                pid = f"prd_sign_{key}_{i + 1:02d}"
                slug = f"sign-{cat['slug']}-{i + 1:02d}"
                lock = 100 + (zlib.crc32(cat["slug"].encode()) % 500) + i  # 카테고리·상품별로 다른 이미지(결정론적)
                cover = _image(conf["kw"], lock)
                gallery = ",".join(_image(conf["kw"], lock + 1000 * g) for g in range(1, 3))
                price = _price(conf["price"][0], conf["price"][1], i)
                compare = int(round(price * 1.15 / 1000) * 1000) if i % 3 == 0 else None
                rating = round(4.2 + (i % 8) * 0.09, 1)
                reviews = (i * 7 + len(cat["slug"])) % 55
                connection.execute(
                    """
                    INSERT OR IGNORE INTO products(
                        id, slug, category_id, org_id, brand, name, description, material, care,
                        image, price, compare_at_price, rating, review_count, created_at,
                        color_family, style_tags, images, is_active
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                    """,
                    (
                        pid, slug, cat["id"], org_id, "SIGN", name,
                        f"SIGN이 제안하는 {conf['noun']}. {mod} 실루엣의 데일리 아이템입니다.",
                        conf["material"], conf["care"], cover, price, compare, rating, reviews, now,
                        COLOR_FAMILY.get(color, "뉴트럴"), conf["tags"], gallery,
                    ),
                )
                inserted_products += 1
                for si, size in enumerate(conf["sizes"]):
                    vid = f"var_{pid}_{si}"
                    sku = f"SIGN-{key.upper()}-{i + 1:02d}-{size}"
                    stock = 4 + (i * 3 + si * 5) % 16
                    if (i + si) % 11 == 0:  # 가끔 품절 옵션
                        stock = 0
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO variants(id, product_id, sku, color, size, price, stock)
                        VALUES(?,?,?,?,?,?,?)
                        """,
                        (vid, pid, sku, color, size, price, stock),
                    )
                    inserted_variants += 1
            print(f"  {cat['name']}({cat['slug']}): 상품 {PER_CATEGORY}개")
    print(f"완료 · org={org_id} · 시도한 상품 {inserted_products}개 / 옵션 {inserted_variants}개")
    print("(멱등: 이미 있는 id는 INSERT OR IGNORE 로 건너뜀)")


if __name__ == "__main__":
    backend = "Postgres" if os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://")) else "SQLite"
    print(f"SIGN 카탈로그 시드 시작 (backend={backend})")
    seed()
