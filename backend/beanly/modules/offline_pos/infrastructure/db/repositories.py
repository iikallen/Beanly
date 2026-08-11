from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosDeviceModel,
    PosOfflineOrderSyncModel,
    PosOfflineSessionModel,
)


class SqlAlchemyOfflinePosRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_device(self, value: PosDeviceModel) -> PosDeviceModel:
        self.session.add(value)
        await self.session.flush()
        return value

    async def list_devices(self, organization_id: UUID) -> list[PosDeviceModel]:
        return list(
            await self.session.scalars(
                select(PosDeviceModel)
                .where(PosDeviceModel.organization_id == organization_id)
                .order_by(PosDeviceModel.name, PosDeviceModel.id)
            )
        )

    async def get_device(
        self, organization_id: UUID, device_id: UUID, *, lock: bool = False
    ) -> PosDeviceModel | None:
        statement = select(PosDeviceModel).where(
            PosDeviceModel.organization_id == organization_id,
            PosDeviceModel.id == device_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_device_by_hash(self, credential_hash: str) -> PosDeviceModel | None:
        return await self.session.scalar(
            select(PosDeviceModel).where(PosDeviceModel.credential_hash == credential_hash)
        )

    async def active_device_for_register(self, register_id: UUID) -> PosDeviceModel | None:
        return await self.session.scalar(
            select(PosDeviceModel).where(
                PosDeviceModel.register_id == register_id,
                PosDeviceModel.status == "ACTIVE",
            )
        )

    async def touch_device(self, device_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(PosDeviceModel)
            .where(PosDeviceModel.id == device_id, PosDeviceModel.status == "ACTIVE")
            .values(last_seen_at=now, updated_at=now)
        )

    async def add_snapshot(self, value: PosCatalogSnapshotModel) -> PosCatalogSnapshotModel:
        self.session.add(value)
        await self.session.flush()
        return value

    async def get_snapshot(
        self, organization_id: UUID, snapshot_id: UUID
    ) -> PosCatalogSnapshotModel | None:
        return await self.session.scalar(
            select(PosCatalogSnapshotModel).where(
                PosCatalogSnapshotModel.organization_id == organization_id,
                PosCatalogSnapshotModel.id == snapshot_id,
            )
        )

    async def add_session(self, value: PosOfflineSessionModel) -> PosOfflineSessionModel:
        self.session.add(value)
        await self.session.flush()
        return value

    async def current_session(self, device_id: UUID) -> PosOfflineSessionModel | None:
        return await self.session.scalar(
            select(PosOfflineSessionModel).where(
                PosOfflineSessionModel.device_id == device_id,
                PosOfflineSessionModel.status == "ACTIVE",
            )
        )

    async def get_session(
        self, device_id: UUID, session_id: UUID, *, lock: bool = False
    ) -> PosOfflineSessionModel | None:
        statement = select(PosOfflineSessionModel).where(
            PosOfflineSessionModel.device_id == device_id,
            PosOfflineSessionModel.id == session_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_sync(
        self, session_id: UUID, client_order_id: UUID, *, lock: bool = False
    ) -> PosOfflineOrderSyncModel | None:
        statement = select(PosOfflineOrderSyncModel).where(
            PosOfflineOrderSyncModel.session_id == session_id,
            PosOfflineOrderSyncModel.client_order_id == client_order_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def save_sync(self, value: PosOfflineOrderSyncModel) -> PosOfflineOrderSyncModel:
        self.session.add(value)
        await self.session.flush()
        return value

    async def pending_for_shift(self, shift_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(PosOfflineOrderSyncModel)
            .join(
                PosOfflineSessionModel,
                PosOfflineSessionModel.id == PosOfflineOrderSyncModel.session_id,
            )
            .where(
                PosOfflineSessionModel.shift_id == shift_id,
                PosOfflineOrderSyncModel.status == "CONFLICT",
            )
        )
        return int(value or 0)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def now(self) -> datetime:
        value = await self.session.scalar(select(func.now()))
        return value if value is not None else datetime.now(UTC)
