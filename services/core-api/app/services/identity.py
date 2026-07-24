from fastapi import HTTPException

from app.services.commerce_client import CommerceClient


def _extract_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return authorization.split(" ", 1)[1].strip()


async def require_identity(
    authorization: str | None, commerce: CommerceClient
) -> dict[str, object]:
    token = _extract_token(authorization)
    profile = await commerce.verify_identity(token)
    if profile is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return profile


async def require_org_access(
    org_id: str, authorization: str | None, commerce: CommerceClient
) -> dict[str, object]:
    """ADMIN can see any org; everyone else must own exactly this one.

    core-api never decodes the customer JWT itself — it asks
    mock-commerce-api (via CommerceClient.verify_identity) whose token this
    is, the same way any other resource server would validate a bearer
    token against its issuer.
    """
    profile = await require_identity(authorization, commerce)
    if profile.get("role") == "ADMIN":
        return profile
    organization = profile.get("organization")
    if not organization or organization.get("id") != org_id:
        raise HTTPException(status_code=403, detail="본인 상점의 데이터만 조회할 수 있습니다.")
    return profile
