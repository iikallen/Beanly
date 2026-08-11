from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.fiscal.application.nkt_dto import NktProduct
from beanly.modules.fiscal.infrastructure.db.models import FiscalNktCacheModel


class NktCacheRepository:
    def __init__(self, session: AsyncSession, *, ttl: timedelta = timedelta(hours=24)) -> None:
        self.session = session
        self.ttl = ttl

    async def search(self, query: str, *, limit: int) -> tuple[NktProduct, ...]:
        now = datetime.now(UTC)
        literal = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{literal}%"
        values = await self.session.scalars(
            select(FiscalNktCacheModel)
            .where(
                FiscalNktCacheModel.expires_at > now,
                or_(
                    FiscalNktCacheModel.name_ru.ilike(pattern, escape="\\"),
                    FiscalNktCacheModel.name_kk.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(FiscalNktCacheModel.name_ru, FiscalNktCacheModel.ntin)
            .limit(limit)
        )
        return tuple(_product(value) for value in values)

    async def by_ntin(self, ntin: str) -> NktProduct | None:
        value = await self.session.scalar(
            select(FiscalNktCacheModel).where(
                FiscalNktCacheModel.ntin == ntin,
                FiscalNktCacheModel.expires_at > datetime.now(UTC),
            )
        )
        return _product(value) if value else None

    async def by_gtin(self, gtin: str) -> tuple[NktProduct, ...]:
        values = await self.session.scalars(
            select(FiscalNktCacheModel).where(
                FiscalNktCacheModel.expires_at > datetime.now(UTC),
                FiscalNktCacheModel.gtins.contains([gtin]),
            )
        )
        return tuple(_product(value) for value in values if gtin in value.gtins)

    async def upsert(self, products: tuple[NktProduct, ...]) -> None:
        now = datetime.now(UTC)
        for product in products:
            value = await self.session.scalar(
                select(FiscalNktCacheModel).where(FiscalNktCacheModel.ntin == product.ntin)
            )
            if value is None:
                value = FiscalNktCacheModel(
                    id=uuid4(),
                    external_product_id=product.external_id,
                    ntin=product.ntin,
                    gtins=list(product.gtins),
                    name_ru=product.name_ru,
                    name_kk=product.name_kk,
                    category_code=product.category_code,
                    unit_code=product.unit_code,
                    status=product.status,
                    source_updated_at=product.updated_at,
                    fetched_at=now,
                    expires_at=now + self.ttl,
                    payload_hash=product.payload_hash,
                )
                try:
                    async with self.session.begin_nested():
                        self.session.add(value)
                        await self.session.flush()
                except IntegrityError:
                    value = await self.session.scalar(
                        select(FiscalNktCacheModel).where(
                            FiscalNktCacheModel.ntin == product.ntin
                        )
                    )
                    if value is None:
                        raise
            value.external_product_id = product.external_id
            value.gtins = list(product.gtins)
            value.name_ru = product.name_ru
            value.name_kk = product.name_kk
            value.category_code = product.category_code
            value.unit_code = product.unit_code
            value.status = product.status
            value.source_updated_at = product.updated_at
            value.fetched_at = now
            value.expires_at = now + self.ttl
            value.payload_hash = product.payload_hash
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _product(value: FiscalNktCacheModel) -> NktProduct:
    return NktProduct(
        value.external_product_id,
        value.ntin,
        tuple(value.gtins),
        value.name_ru,
        value.name_kk,
        value.category_code,
        value.unit_code,
        value.status,
        value.source_updated_at,
        value.payload_hash,
    )
