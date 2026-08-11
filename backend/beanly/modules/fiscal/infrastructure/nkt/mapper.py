import hashlib
import json
from datetime import UTC, datetime

from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.fiscal.domain.exceptions import NktInvalidResponse


def map_product(payload: object) -> NktProduct:
    if not isinstance(payload, dict):
        raise NktInvalidResponse("NKT returned an invalid product")
    try:
        external_id = _text(payload["id"], "id")
        ntin = _tin(payload["ntin"], "ntin")
        name_ru = _text(payload["nameRu"], "nameRu")
        name_kk = _text(payload["nameKk"], "nameKk")
        ancestors = payload["categoryAncestors"]
        if not isinstance(ancestors, list) or not ancestors:
            raise ValueError("categoryAncestors")
        category = ancestors[-1]
        if not isinstance(category, dict):
            raise ValueError("categoryAncestors")
        category_code = _text(category["code"], "category code")
    except (KeyError, TypeError, ValueError) as exc:
        raise NktInvalidResponse("NKT returned an invalid product") from exc
    gtin_value = payload.get("gtin")
    gtins = (_tin(gtin_value, "gtin"),) if gtin_value not in (None, "") else ()
    updated_at = _datetime(payload.get("updatedDate"))
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return NktProduct(
        external_id=external_id,
        ntin=ntin,
        gtins=gtins,
        name_ru=name_ru,
        name_kk=name_kk,
        category_code=category_code,
        unit_code=None,
        status="UNKNOWN",
        updated_at=updated_at,
        payload_hash=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def _text(value: object, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(field)
    return normalized


def _tin(value: object, field: str) -> str:
    normalized = _text(value, field)
    if len(normalized) != 13 or not normalized.isascii() or not normalized.isdecimal():
        raise ValueError(field)
    return normalized


def _datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise NktInvalidResponse("NKT returned an invalid updatedDate") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)
