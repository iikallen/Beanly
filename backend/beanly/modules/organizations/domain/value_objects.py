from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from beanly.modules.organizations.domain.exceptions import InvalidTimezone


def normalize_country_code(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 2 or not normalized.isalpha() or not normalized.isascii():
        raise ValueError("Country code must contain two ASCII letters")
    return normalized


def normalize_currency_code(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
        raise ValueError("Currency code must contain three ASCII letters")
    return normalized


def normalize_timezone(value: str) -> str:
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezone("Timezone must be a valid IANA timezone") from exc
    return normalized
