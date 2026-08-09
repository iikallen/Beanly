def normalized_name(value: str, maximum: int) -> str:
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError(f"Name must contain between 1 and {maximum} characters")
    return result


def normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None
