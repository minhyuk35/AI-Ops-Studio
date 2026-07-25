"""AI 추천 · 코디 조합 엔진 — deterministic pairwise combo scoring.

See docs/ai-recommendation-plan.html#s3 (B-1) for the design this implements.
AI only tags each product ONCE (color_family/style_tags, at creation time via
the Langfuse `product-style-tagger` persona in core-api) -- the pairwise
combo score itself is always computed here, by code, from those tags plus a
seed compatibility table grounded in color theory / casual-streetwear
styling conventions. This is the same "코드는 계산, AI는 해석" split used
everywhere else in this project: interpretation happens once per product,
not once per pair.
"""

from __future__ import annotations

COLOR_FAMILIES = ("뉴트럴", "데님/인디고", "어스톤", "파스텔", "비비드")

# Symmetric 0..1 compatibility score per unordered color-family pair. Values
# come straight from docs/ai-recommendation-plan.html#s3's seed table: 뉴트럴
# is the anchor (strong with everything), 비비드+비비드/파스텔 clash, denim
# and earth tones share the beige/brown overlap, etc.
_COLOR_COMPATIBILITY: dict[frozenset[str], float] = {
    frozenset({"뉴트럴"}): 0.70,
    frozenset({"뉴트럴", "데님/인디고"}): 0.90,
    frozenset({"뉴트럴", "어스톤"}): 0.90,
    frozenset({"뉴트럴", "파스텔"}): 0.90,
    frozenset({"뉴트럴", "비비드"}): 0.90,
    frozenset({"데님/인디고"}): 0.55,
    frozenset({"데님/인디고", "어스톤"}): 0.80,
    frozenset({"데님/인디고", "파스텔"}): 0.50,
    frozenset({"데님/인디고", "비비드"}): 0.50,
    frozenset({"어스톤"}): 0.65,
    frozenset({"어스톤", "파스텔"}): 0.45,
    frozenset({"어스톤", "비비드"}): 0.35,
    frozenset({"파스텔"}): 0.55,
    frozenset({"파스텔", "비비드"}): 0.15,
    frozenset({"비비드"}): 0.15,
}

STYLE_MOODS = ("미니멀", "캐주얼", "스트릿·힙", "러블리·청순", "포멀", "스포티")

_STYLE_ADJACENT: dict[str, set[str]] = {
    "미니멀": {"포멀"},
    "캐주얼": {"스트릿·힙", "러블리·청순"},
    "스트릿·힙": {"캐주얼"},
    "러블리·청순": {"캐주얼"},
    "포멀": {"미니멀"},
    "스포티": {"캐주얼"},
}

_STYLE_CONFLICTING: dict[str, set[str]] = {
    "미니멀": {"스트릿·힙"},
    "캐주얼": {"포멀"},
    "스트릿·힙": {"포멀", "러블리·청순"},
    "러블리·청순": {"스트릿·힙", "스포티"},
    "포멀": {"스트릿·힙", "스포티"},
    "스포티": {"포멀", "러블리·청순"},
}

# 조합 점수 가중치 (docs/ai-recommendation-plan.html#s3의 "구체적 점수 계산").
_COLOR_WEIGHT = 0.5
_STYLE_WEIGHT = 0.3
_CATEGORY_WEIGHT = 0.2

_NEUTRAL_SCORE = 0.5


def color_score(family_a: str | None, family_b: str | None) -> float:
    if not family_a or not family_b:
        return _NEUTRAL_SCORE
    return _COLOR_COMPATIBILITY.get(frozenset({family_a, family_b}), _NEUTRAL_SCORE)


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _mood_pair_score(mood_a: str, mood_b: str) -> float:
    if mood_a == mood_b:
        return 0.9
    if mood_b in _STYLE_ADJACENT.get(mood_a, set()):
        return 0.7
    if mood_b in _STYLE_CONFLICTING.get(mood_a, set()):
        return 0.2
    return _NEUTRAL_SCORE


def style_score(tags_a: str | None, tags_b: str | None) -> float:
    moods_a, moods_b = _parse_tags(tags_a), _parse_tags(tags_b)
    if not moods_a or not moods_b:
        return _NEUTRAL_SCORE
    # 여러 무드 태그 중 가장 잘 맞는 조합 하나만 있어도 그 조합이 성립한다고 봄
    # (둘 다 "캐주얼,스트릿·힙"이면 최고 매치는 당연히 캐주얼-캐주얼).
    return max(_mood_pair_score(a, b) for a in moods_a for b in moods_b)


def category_score(top_level_a: str | None, top_level_b: str | None) -> float:
    """상의+하의처럼 착용 부위가 다르면 가점, 상의+상의처럼 같으면 감점."""
    if not top_level_a or not top_level_b:
        return _NEUTRAL_SCORE
    return 0.85 if top_level_a != top_level_b else 0.25


def combo_score(
    *,
    color_family_a: str | None,
    color_family_b: str | None,
    style_tags_a: str | None,
    style_tags_b: str | None,
    top_level_a: str | None,
    top_level_b: str | None,
) -> float:
    """0..100 baseline (seed) combo score for a product pair -- no signals yet."""
    total = (
        _COLOR_WEIGHT * color_score(color_family_a, color_family_b)
        + _STYLE_WEIGHT * style_score(style_tags_a, style_tags_b)
        + _CATEGORY_WEIGHT * category_score(top_level_a, top_level_b)
    )
    return round(total * 100, 2)


def pair_key(product_id_a: str, product_id_b: str) -> tuple[str, str]:
    """Order-independent key so (A,B) and (B,A) resolve to the same pair."""
    if product_id_a <= product_id_b:
        return (product_id_a, product_id_b)
    return (product_id_b, product_id_a)
