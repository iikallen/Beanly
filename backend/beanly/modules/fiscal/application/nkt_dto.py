from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NktProduct:
    external_id: str
    ntin: str
    gtins: tuple[str, ...]
    name_ru: str
    name_kk: str
    category_code: str
    unit_code: str | None
    status: str
    updated_at: datetime | None
    payload_hash: str
