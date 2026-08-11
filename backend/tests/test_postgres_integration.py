import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from beanly.core.config.settings import Settings
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import (
    OutboxLeaseLost,
    OutboxRepository,
)
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.events.registry import to_envelope
from beanly.core.security.tokens import hash_invitation_token
from beanly.modules.employees.infrastructure.db.models import EmployeeModel
from beanly.modules.employees.infrastructure.db.repositories import (
    SqlAlchemyEmployeeRepository,
)
from beanly.modules.inventory.application.commands import (
    CreateAndPostCommand,
    CreateDraftCommand,
    QuantityInput,
)
from beanly.modules.inventory.application.operations import (
    InventoryOperationsService,
    OperationLineInput,
)
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.domain.enums import InventoryCountType, InventoryTransactionType
from beanly.modules.inventory.domain.exceptions import (
    IdempotencyConflict,
    InvalidInventoryOperation,
    InventoryCountChanged,
)
from beanly.modules.inventory.domain.value_objects import UnitCode
from beanly.modules.inventory.infrastructure.db.operation_repository import (
    SqlAlchemyInventoryOperationsRepository,
)
from beanly.modules.inventory.infrastructure.db.repositories import (
    SqlAlchemyInventoryRepository,
)
from beanly.modules.menu.application.commands import (
    ModifierComponentInput,
    RecipeComponentInput,
    VariantInput,
)
from beanly.modules.menu.application.services import MenuService
from beanly.modules.menu.domain.enums import ModifierSelectionType
from beanly.modules.menu.domain.exceptions import InvalidMenuOperation
from beanly.modules.menu.infrastructure.db.repositories import SqlAlchemyMenuRepository
from beanly.modules.menu.infrastructure.inventory_gateway import (
    InventoryApplicationGateway as MenuInventoryGateway,
)
from beanly.modules.organizations.application.commands.accept_invitation import (
    AcceptInvitationCommand,
)
from beanly.modules.organizations.application.commands.create_organization import (
    CreateOrganizationCommand,
)
from beanly.modules.organizations.application.services.invitation_service import (
    InvitationService,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import OrganizationInvitation, TenantContext
from beanly.modules.organizations.domain.enums import (
    InvitationStatus,
    LocationAccess,
    MembershipRole,
)
from beanly.modules.organizations.domain.exceptions import (
    DuplicateMembership,
    InvitationAlreadyAccepted,
)
from beanly.modules.organizations.domain.permissions import permissions_for
from beanly.modules.organizations.infrastructure.db.invitation_repository import (
    SqlAlchemyInvitationRepository,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.payments.application.payment_service import (
    CompletePaymentInput,
    PaymentLineInput,
    PaymentService,
)
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.events import PaymentCompleted
from beanly.modules.payments.domain.exceptions import (
    OrderAlreadyPaid,
    PaymentIdempotencyConflict,
)
from beanly.modules.payments.infrastructure.db.repositories import (
    SqlAlchemyPaymentRepository,
)
from beanly.modules.payments.infrastructure.inventory_gateway import (
    InventorySaleGateway,
    SalesOrderReferenceValidator,
)
from beanly.modules.payments.infrastructure.sales_gateway import SalesSettlementGateway
from beanly.modules.purchasing.application.commands import (
    CreateGoodsReceiptCommand,
    CreatePurchaseOrderCommand,
    PurchaseLineInput,
    ReceiptLineInput,
    SupplierInput,
)
from beanly.modules.purchasing.application.services import PurchasingService
from beanly.modules.purchasing.domain.enums import GoodsReceiptStatus, PurchaseOrderStatus
from beanly.modules.purchasing.domain.exceptions import InvalidPurchasingOperation
from beanly.modules.purchasing.infrastructure.db.repositories import (
    SqlAlchemyPurchasingRepository,
)
from beanly.modules.purchasing.infrastructure.inventory_gateway import (
    InventoryApplicationGateway,
    PurchasingReferenceValidator,
)
from beanly.modules.sales.application.commands import AddOrderItemInput, CreateOrderInput
from beanly.modules.sales.application.order_service import OrderService
from beanly.modules.sales.application.ports import (
    SellableComponentSnapshot,
    SellableItemSnapshot,
)
from beanly.modules.sales.application.register_service import RegisterService
from beanly.modules.sales.application.shift_service import ShiftService
from beanly.modules.sales.domain.enums import OrderType
from beanly.modules.sales.domain.exceptions import ShiftHasOpenOrders
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository
from beanly.modules.sales.infrastructure.inventory_gateway import InventorySalesGateway

ORGANIZATION_TABLES = {"organizations", "locations", "organization_memberships"}
TEAM_TABLES = {
    "employees",
    "employee_locations",
    "membership_locations",
    "organization_invitations",
    "organization_invitation_locations",
}
INVENTORY_CORE_TABLES = {"warehouses", "inventory_items", "stock_balances"}
INVENTORY_LEDGER_TABLES = {
    "inventory_transactions",
    "inventory_transaction_lines",
}
PURCHASING_TABLES = {
    "suppliers",
    "purchase_orders",
    "purchase_order_lines",
    "goods_receipts",
    "goods_receipt_lines",
}
MENU_TABLES = {
    "menu_categories",
    "products",
    "product_variants",
    "variant_prices",
    "product_location_settings",
    "recipes",
    "recipe_components",
}
MENU_MODIFIER_TABLES = {
    "modifier_groups",
    "modifier_options",
    "modifier_option_components",
    "modifier_option_prices",
    "modifier_option_location_settings",
}
MENU_TABLES |= MENU_MODIFIER_TABLES
SALES_TABLES = {
    "pos_registers",
    "register_shifts",
    "sales_orders",
    "sales_order_items",
    "sales_order_item_modifiers",
    "sales_order_item_components",
}
PAYMENT_TABLES = {"payments", "payment_lines"}
OUTBOX_TABLES = {"outbox_events"}
INVENTORY_OPERATION_TABLES = {
    "inventory_writeoff_reasons",
    "inventory_writeoffs",
    "inventory_writeoff_lines",
    "inventory_counts",
    "inventory_count_lines",
    "inventory_transfers",
    "inventory_transfer_lines",
    "supplier_returns",
    "supplier_return_lines",
}
FINANCE_TABLES = {
    "expense_categories",
    "expenses",
    "finance_entries",
    "cash_accounts",
    "cash_entries",
    "cash_movements",
}
OFFLINE_POS_TABLES = {
    "pos_devices",
    "pos_catalog_snapshots",
    "pos_offline_sessions",
    "pos_offline_order_syncs",
}
APPLICATION_TABLES = (
    ORGANIZATION_TABLES
    | TEAM_TABLES
    | INVENTORY_CORE_TABLES
    | INVENTORY_LEDGER_TABLES
    | PURCHASING_TABLES
    | MENU_TABLES
    | SALES_TABLES
    | PAYMENT_TABLES
    | OUTBOX_TABLES
    | INVENTORY_OPERATION_TABLES
    | FINANCE_TABLES
    | OFFLINE_POS_TABLES
)


class FailingOutboxRepository(OutboxRepository):
    async def add_many(self, envelopes):
        await super().add_many(envelopes)
        raise RuntimeError("forced outbox failure")


async def database_snapshot(database_url: str) -> dict:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_inspect_schema)
    finally:
        await engine.dispose()


def _inspect_schema(sync) -> dict:
    inspector = inspect(sync)
    tables = set(inspector.get_table_names())
    columns = {
        table: {column["name"]: column for column in inspector.get_columns(table)}
        for table in tables
        if table != "alembic_version"
    }
    indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in APPLICATION_TABLES & tables
    }
    foreign_keys = {
        table: {
            (tuple(key["constrained_columns"]), key["referred_table"])
            for key in inspector.get_foreign_keys(table)
        }
        for table in APPLICATION_TABLES & tables
    }
    unique_constraints = {
        table: {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table)
        }
        for table in APPLICATION_TABLES & tables
    }
    check_constraints = {
        table: {constraint["name"] for constraint in inspector.get_check_constraints(table)}
        for table in APPLICATION_TABLES & tables
    }
    primary_keys = {
        table: tuple(inspector.get_pk_constraint(table)["constrained_columns"])
        for table in APPLICATION_TABLES & tables
    }
    revision = sync.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    sequences = set(inspector.get_sequence_names())
    return {
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
        "unique_constraints": unique_constraints,
        "check_constraints": check_constraints,
        "primary_keys": primary_keys,
        "revision": revision,
        "sequences": sequences,
    }


def alembic_config(database_url: str) -> Config:
    config = Config(str(Path("alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def assert_real_transaction_rollback(database_url: str) -> None:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    try:
        async with engine.connect() as connection:
            baseline = {
                table: await connection.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in ORGANIZATION_TABLES
            }
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        is_active, email_verified, created_at, updated_at
                    ) VALUES (
                        :id, :email, :password_hash, 'Atomic', 'Owner',
                        true, false, now(), now()
                    )
                    """
                ),
                {
                    "id": user_id,
                    "email": f"atomic-{user_id}@example.com",
                    "password_hash": "not-used-in-this-test",
                },
            )

        class FailingLocationRepository(SqlAlchemyOrganizationRepository):
            async def add_location(self, location):
                raise RuntimeError("forced location failure")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            service = OrganizationService(FailingLocationRepository(session))
            with pytest.raises(RuntimeError, match="forced location failure"):
                await service.create_workspace(
                    CreateOrganizationCommand(
                        user_id=user_id,
                        name="Atomic Coffee",
                        country_code="KZ",
                        currency_code="KZT",
                        location_name="Dostyk",
                        timezone="Asia/Almaty",
                    )
                )
            counts = {
                table: await session.scalar(text(f"SELECT count(*) FROM {table}"))
                for table in ORGANIZATION_TABLES
            }
        assert counts == baseline
    finally:
        await engine.dispose()


async def seed_stage_two_owner(database_url: str) -> tuple:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    organization_id = uuid4()
    location_id = uuid4()
    membership_id = uuid4()
    try:
        async with engine.begin() as connection:
            values = {
                "user_id": user_id,
                "email": f"legacy-{user_id}@example.com",
                "organization_id": organization_id,
                "location_id": location_id,
                "membership_id": membership_id,
            }
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        is_active, email_verified, created_at, updated_at
                    ) VALUES (
                        :user_id, :email, 'not-used', 'Legacy', 'Owner',
                        true, false, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO organizations (
                        id, name, country_code, currency_code, status,
                        created_by, created_at, updated_at
                    ) VALUES (
                        :organization_id, 'Legacy Coffee', 'KZ', 'KZT', 'active',
                        :user_id, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO locations (
                        id, organization_id, name, timezone, address,
                        is_active, is_primary, created_at, updated_at
                    ) VALUES (
                        :location_id, :organization_id, 'Legacy', 'Asia/Almaty', NULL,
                        true, true, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO organization_memberships (
                        id, organization_id, user_id, role, status, created_at, updated_at
                    ) VALUES (
                        :membership_id, :organization_id, :user_id,
                        'OWNER', 'active', now(), now()
                    )
                    """
                ),
                values,
            )
        return user_id, organization_id, location_id, membership_id
    finally:
        await engine.dispose()


async def membership_state(database_url: str, membership_id) -> tuple[str, str | None]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, location_access FROM organization_memberships "
                        "WHERE id = :membership_id"
                    ),
                    {"membership_id": membership_id},
                )
            ).one()
            return row.status, row.location_access
    finally:
        await engine.dispose()


async def seed_legacy_inventory_ledger(
    database_url: str,
    user_id: UUID,
    organization_id: UUID,
    location_id: UUID,
) -> tuple[UUID, UUID]:
    engine = create_async_engine(database_url)
    warehouse_id = uuid4()
    item_id = uuid4()
    transaction_id = uuid4()
    line_id = uuid4()
    try:
        async with engine.begin() as connection:
            values = {
                "warehouse_id": warehouse_id,
                "organization_id": organization_id,
                "location_id": location_id,
                "item_id": item_id,
                "balance_id": uuid4(),
                "transaction_id": transaction_id,
                "user_id": user_id,
                "line_id": line_id,
            }
            statements = (
                """
                    INSERT INTO warehouses (
                        id, organization_id, location_id, name, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :warehouse_id, :organization_id, :location_id,
                        'Legacy warehouse', true, now(), now()
                    )
                """,
                """
                    INSERT INTO inventory_items (
                        id, organization_id, name, sku, base_unit, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :item_id, :organization_id, 'Legacy item', 'LEGACY', 'pcs',
                        true, now(), now()
                    )
                """,
                """
                    INSERT INTO stock_balances (
                        id, organization_id, location_id, warehouse_id,
                        inventory_item_id, quantity, updated_at
                    ) VALUES (
                        :balance_id, :organization_id, :location_id, :warehouse_id,
                        :item_id, 10, now()
                    )
                """,
                """
                    INSERT INTO inventory_transactions (
                        id, organization_id, location_id, warehouse_id, type, status,
                        note, created_by, created_at, posted_at
                    ) VALUES (
                        :transaction_id, :organization_id, :location_id, :warehouse_id,
                        'OPENING_BALANCE', 'POSTED', 'Legacy opening', :user_id,
                        now(), now()
                    )
                """,
                """
                    INSERT INTO inventory_transaction_lines (
                        id, transaction_id, inventory_item_id, quantity_delta,
                        unit_cost_amount, created_at
                    ) VALUES (
                        :line_id, :transaction_id, :item_id, 10, 2, now()
                    )
                """,
            )
            for statement in statements:
                await connection.execute(text(statement), values)
        return warehouse_id, line_id
    finally:
        await engine.dispose()


async def assert_postgres_invitation_parent_is_flushed_first(database_url: str) -> None:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    member_user_id = uuid4()
    raw_token = "postgres-concurrent-invitation-token"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        is_active, email_verified, created_at, updated_at
                    ) VALUES (
                        :id, :email, 'not-used', 'Invite', 'Owner',
                        true, false, now(), now()
                    )
                    """
                ),
                {"id": user_id, "email": f"invite-{user_id}@example.com"},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        is_active, email_verified, created_at, updated_at
                    ) VALUES (
                        :id, 'concurrent-member@example.com', 'not-used',
                        'Concurrent', 'Member', true, false, now(), now()
                    )
                    """
                ),
                {"id": member_user_id},
            )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            workspace = await OrganizationService(
                SqlAlchemyOrganizationRepository(session)
            ).create_workspace(
                CreateOrganizationCommand(
                    user_id=user_id,
                    name="Invitation Coffee",
                    country_code="KZ",
                    currency_code="KZT",
                    location_name="Dostyk",
                    timezone="Asia/Almaty",
                )
            )
            now = datetime.now(UTC)
            repository = SqlAlchemyInvitationRepository(session)
            invitation = OrganizationInvitation(
                id=uuid4(),
                organization_id=workspace.organization.id,
                employee_id=None,
                email="concurrent-member@example.com",
                role=MembershipRole.BARISTA,
                token_hash=hash_invitation_token(raw_token),
                status=InvitationStatus.PENDING,
                expires_at=now + timedelta(days=7),
                invited_by=user_id,
                accepted_by=None,
                accepted_at=None,
                location_ids=(workspace.location.id,),
                created_at=now,
            )
            await repository.add(invitation)
            await repository.commit()
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM organization_invitation_locations "
                        "WHERE invitation_id = :id"
                    ),
                    {"id": invitation.id},
                )
                == 1
            )
        class NoopEmailSender:
            async def send_invitation(self, email, organization_name, role, invite_url):
                raise AssertionError("Acceptance must not send invitation email")

        async def accept_once() -> str:
            async with sessions() as session:
                service = InvitationService(
                    invitations=SqlAlchemyInvitationRepository(session),
                    organizations=SqlAlchemyOrganizationRepository(session),
                    employees=SqlAlchemyEmployeeRepository(session),
                    email_sender=NoopEmailSender(),
                    settings=Settings(),
                )
                try:
                    await service.accept(
                        AcceptInvitationCommand(
                            token=raw_token,
                            user_id=member_user_id,
                            user_email="concurrent-member@example.com",
                            first_name="Concurrent",
                            last_name="Member",
                        )
                    )
                    return "accepted"
                except (InvitationAlreadyAccepted, DuplicateMembership):
                    return "rejected"

        results = await asyncio.gather(accept_once(), accept_once())
        assert sorted(results) == ["accepted", "rejected"]

        async with sessions() as session:
            membership_id = await session.scalar(
                text(
                    "SELECT id FROM organization_memberships "
                    "WHERE organization_id = :organization_id AND user_id = :user_id"
                ),
                {
                    "organization_id": workspace.organization.id,
                    "user_id": member_user_id,
                },
            )
            assert membership_id is not None
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM membership_locations "
                        "WHERE membership_id = :membership_id"
                    ),
                    {"membership_id": membership_id},
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(EmployeeModel)
                    .where(EmployeeModel.user_id == member_user_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM organization_invitations "
                        "WHERE id = :invitation_id AND status = 'ACCEPTED'"
                    ),
                    {"invitation_id": invitation.id},
                )
                == 1
            )
    finally:
        await engine.dispose()


async def seed_inventory_context(
    database_url: str,
) -> tuple[TenantContext, UUID, UUID]:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    organization_id = uuid4()
    location_id = uuid4()
    warehouse_id = uuid4()
    item_id = uuid4()
    values = {
        "user_id": user_id,
        "email": f"inventory-pg-{user_id}@example.com",
        "organization_id": organization_id,
        "location_id": location_id,
        "membership_id": uuid4(),
        "warehouse_id": warehouse_id,
        "item_id": item_id,
    }
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, password_hash, first_name, last_name,
                        is_active, email_verified, created_at, updated_at
                    ) VALUES (
                        :user_id, :email, 'not-used', 'Inventory', 'Owner',
                        true, false, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO organizations (
                        id, name, country_code, currency_code, status,
                        created_by, created_at, updated_at
                    ) VALUES (
                        :organization_id, 'Postgres Inventory', 'KZ', 'KZT', 'active',
                        :user_id, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO locations (
                        id, organization_id, name, timezone, address,
                        is_active, is_primary, created_at, updated_at
                    ) VALUES (
                        :location_id, :organization_id, 'Main', 'Asia/Almaty', NULL,
                        true, true, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO organization_memberships (
                        id, organization_id, user_id, role, status, location_access,
                        created_at, updated_at
                    ) VALUES (
                        :membership_id, :organization_id, :user_id,
                        'OWNER', 'ACTIVE', 'ALL', now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO warehouses (
                        id, organization_id, location_id, name, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :warehouse_id, :organization_id, :location_id, 'Main', true,
                        now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO inventory_items (
                        id, organization_id, name, sku, base_unit, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :item_id, :organization_id, 'Coffee', 'PG-COFFEE', 'g', true,
                        now(), now()
                    )
                    """
                ),
                values,
            )
    finally:
        await engine.dispose()
    return (
        TenantContext(
            user_id,
            organization_id,
            values["membership_id"],
            MembershipRole.OWNER,
            permissions_for(MembershipRole.OWNER),
            LocationAccess.ALL,
        ),
        warehouse_id,
        item_id,
    )


@pytest_asyncio.fixture
async def postgres_inventory_database():
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")
    database_name = f"beanly_inventory_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        await asyncio.to_thread(command.upgrade, alembic_config(test_url), "head")
        yield test_url
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()


@pytest.mark.anyio
async def test_postgres_outbox_delivery_retry_lease_and_concurrent_claims(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, _, _ = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def add_events(count: int) -> tuple[UUID, ...]:
        envelopes = tuple(
            to_envelope(
                PaymentCompleted(
                    uuid4(),
                    uuid4(),
                    context.organization_id,
                    uuid4(),
                    1000 + index,
                )
            )
            for index in range(count)
        )
        async with sessions() as session:
            await OutboxRepository(session).add_many(envelopes)
            await session.commit()
        return tuple(envelope.id for envelope in envelopes)

    try:
        event_ids = await add_events(100)
        deliveries: dict[UUID, int] = {}

        async def record(envelope) -> None:
            deliveries[envelope.id] = deliveries.get(envelope.id, 0) + 1
            await asyncio.sleep(0)

        handlers = EventHandlerRegistry()
        handlers.register("payment.completed", 1, record)
        async with sessions() as first, sessions() as second:
            results = await asyncio.gather(
                OutboxDispatcher(
                    OutboxRepository(first), handlers, "worker-a", batch_size=50
                ).run_once(),
                OutboxDispatcher(
                    OutboxRepository(second), handlers, "worker-b", batch_size=50
                ).run_once(),
            )
        assert sorted(results) == [50, 50]
        assert set(deliveries) == set(event_ids)
        assert set(deliveries.values()) == {1}
        async with sessions() as session:
            assert await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.id.in_(event_ids),
                    OutboxEventModel.processed_at.is_not(None),
                    OutboxEventModel.attempts == 0,
                )
            ) == 100

        no_handler_id = (await add_events(1))[0]
        async with sessions() as session:
            assert await OutboxDispatcher(
                OutboxRepository(session), EventHandlerRegistry(), "worker-empty"
            ).run_once() == 1
        async with sessions() as session:
            no_handler = await session.get(OutboxEventModel, no_handler_id)
            assert no_handler is not None and no_handler.processed_at is not None

        flaky_id = (await add_events(1))[0]
        flaky_calls = 0

        async def flaky(_envelope) -> None:
            nonlocal flaky_calls
            flaky_calls += 1
            if flaky_calls < 3:
                raise RuntimeError("temporary handler failure")

        flaky_handlers = EventHandlerRegistry()
        flaky_handlers.register("payment.completed", 1, flaky)
        async with sessions() as session:
            dispatcher = OutboxDispatcher(
                OutboxRepository(session), flaky_handlers, "worker-flaky"
            )
            for attempt in range(3):
                assert await dispatcher.run_once() == 1
                if attempt < 2:
                    failed = await session.get(OutboxEventModel, flaky_id)
                    assert failed is not None
                    assert failed.attempts == attempt + 1
                    assert failed.processed_at is None
                    assert failed.last_error == (
                        "RuntimeError: temporary handler failure"
                    )
                    assert failed.available_at > failed.occurred_at
                    assert failed.locked_by is None
                    assert failed.locked_until is None
                    await session.execute(
                        text(
                            "UPDATE outbox_events SET available_at=now()-interval '1 second' "
                            "WHERE id=:event_id"
                        ),
                        {"event_id": flaky_id},
                    )
                    await session.commit()
            flaky_model = await session.get(OutboxEventModel, flaky_id)
            assert flaky_model is not None
            assert flaky_model.attempts == 2
            assert flaky_model.processed_at is not None
            assert flaky_model.dead_lettered_at is None
            assert flaky_model.last_error is None

        dead_id = (await add_events(1))[0]

        async def poison(_envelope) -> None:
            raise RuntimeError("x" * 5000)

        poison_handlers = EventHandlerRegistry()
        poison_handlers.register("payment.completed", 1, poison)
        async with sessions() as session:
            dispatcher = OutboxDispatcher(
                OutboxRepository(session),
                poison_handlers,
                "worker-poison",
                max_attempts=12,
            )
            for attempt in range(12):
                assert await dispatcher.run_once() == 1
                if attempt < 11:
                    await session.execute(
                        text(
                            "UPDATE outbox_events SET available_at=now()-interval '1 second' "
                            "WHERE id=:event_id"
                        ),
                        {"event_id": dead_id},
                    )
                    await session.commit()
            dead_model = await session.get(OutboxEventModel, dead_id)
            assert dead_model is not None
            assert dead_model.attempts == 12
            assert dead_model.processed_at is None
            assert dead_model.dead_lettered_at is not None
            assert dead_model.locked_by is None
            assert dead_model.locked_until is None
            assert dead_model.last_error is not None
            assert len(dead_model.last_error) == 4000
            assert await dispatcher.run_once() == 0

        lease_id = (await add_events(1))[0]
        claimed_at = datetime.now(UTC) + timedelta(seconds=1)
        async with sessions() as first, sessions() as second:
            first_repository = OutboxRepository(first)
            second_repository = OutboxRepository(second)
            assert len(
                await first_repository.claim_batch(
                    "worker-lease-a", 1, 30, now=claimed_at
                )
            ) == 1
            await first.commit()
            assert await second_repository.claim_batch(
                "worker-lease-b", 1, 30, now=claimed_at + timedelta(seconds=29)
            ) == ()
            await second.commit()
            reclaimed = await second_repository.claim_batch(
                "worker-lease-b", 1, 30, now=claimed_at + timedelta(seconds=31)
            )
            assert tuple(value.id for value in reclaimed) == (lease_id,)
            await second.commit()
            with pytest.raises(OutboxLeaseLost):
                await first_repository.mark_processed(
                    lease_id,
                    "worker-lease-a",
                    now=claimed_at + timedelta(seconds=32),
                )
            await first.rollback()
            await second_repository.mark_processed(
                lease_id,
                "worker-lease-b",
                now=claimed_at + timedelta(seconds=32),
            )
            await second.commit()
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_inventory_concurrency_idempotency_and_reconciliation(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def command_for(
        quantity: str,
        key: str,
        *,
        type_: InventoryTransactionType = InventoryTransactionType.ADJUSTMENT,
        note: str = "Postgres movement",
    ) -> CreateAndPostCommand:
        return CreateAndPostCommand(
            context.organization_id,
            context.user_id,
            warehouse_id,
            type_,
            note,
            (QuantityInput(item_id, Decimal(quantity), UnitCode.G),),
            key,
        )

    async def execute(command_: CreateAndPostCommand):
        async with sessions() as session:
            return await InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
                OutboxEventSink(OutboxRepository(session)),
            ).create_and_post(context, command_)

    async def balance() -> Decimal:
        async with sessions() as session:
            value = await session.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            )
            return value or Decimal(0)

    try:
        opening = await execute(
            command_for(
                "1000",
                "pg:opening",
                type_=InventoryTransactionType.OPENING_BALANCE,
                note="Opening balance",
            )
        )
        assert await balance() == Decimal("1000")

        async with sessions() as session:
            service = InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
                OutboxEventSink(OutboxRepository(session)),
            )
            draft = await service.create_draft(
                context,
                CreateDraftCommand(
                    context.organization_id,
                    context.user_id,
                    warehouse_id,
                    InventoryTransactionType.ADJUSTMENT,
                    "Draft does not move stock",
                    (QuantityInput(item_id, Decimal("-10"), UnitCode.G),),
                    "pg:draft",
                ),
            )
            assert await balance() == Decimal("1000")
            await service.post_transaction(context, draft.transaction.id)
            await service.post_transaction(context, draft.transaction.id)
        assert await balance() == Decimal("990")

        concurrent = await asyncio.gather(
            *(execute(command_for("-10", f"pg:concurrent:{index}")) for index in range(20))
        )
        assert len({detail.transaction.id for detail in concurrent}) == 20
        assert await balance() == Decimal("790")

        same_key = await asyncio.gather(
            *(execute(command_for("-5", "pg:idempotent")) for _ in range(20))
        )
        assert len({detail.transaction.id for detail in same_key}) == 1
        assert await balance() == Decimal("785")
        with pytest.raises(IdempotencyConflict):
            await execute(command_for("-6", "pg:idempotent"))

        original_id = concurrent[0].transaction.id

        async def reverse_once():
            async with sessions() as session:
                return await InventoryService(
                    SqlAlchemyInventoryRepository(session),
                    OrganizationService(SqlAlchemyOrganizationRepository(session)),
                    OutboxEventSink(OutboxRepository(session)),
                ).reverse(context, original_id, "pg:reverse")

        reversals = await asyncio.gather(reverse_once(), reverse_once())
        assert reversals[0].transaction.id == reversals[1].transaction.id
        assert await balance() == Decimal("795")
        async with sessions() as session:
            service = InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            )
            with pytest.raises(InvalidInventoryOperation):
                await service.reverse(context, original_id, "pg:reverse:different")

        await execute(command_for("0.100001", "pg:precision:1"))
        await execute(command_for("0.200002", "pg:precision:2"))
        assert await balance() == Decimal("795.300003")

        class FailAfterBalanceRepository(SqlAlchemyInventoryRepository):
            async def mark_status(self, organization_id, transaction_id, status, posted_at):
                raise RuntimeError("forced failure after balance UPSERT")

        async with sessions() as session:
            failing = InventoryService(
                FailAfterBalanceRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            )
            with pytest.raises(RuntimeError, match="forced failure"):
                await failing.create_and_post(context, command_for("100", "pg:forced-rollback"))
        assert await balance() == Decimal("795.300003")

        async with sessions() as session:
            assert (
                await session.execute(
                    select(OutboxEventModel.event_name)
                    .where(OutboxEventModel.aggregate_id == opening.transaction.id)
                    .order_by(OutboxEventModel.event_name)
                )
            ).scalars().all() == [
                "inventory.transaction_posted",
                "inventory.valuation_changed",
            ]
            assert await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.event_name == "inventory.cost_updated"
                )
            ) > 0
            ledger = await session.scalar(
                text(
                    """
                    SELECT COALESCE(SUM(line.quantity_delta), 0)
                    FROM inventory_transaction_lines line
                    JOIN inventory_transactions tx ON tx.id = line.transaction_id
                    WHERE tx.organization_id = :organization_id
                      AND tx.warehouse_id = :warehouse_id
                      AND line.inventory_item_id = :item_id
                      AND tx.status IN ('POSTED', 'REVERSED')
                    """
                ),
                {
                    "organization_id": context.organization_id,
                    "warehouse_id": warehouse_id,
                    "item_id": item_id,
                },
            )
            failed_count = await session.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions "
                    "WHERE organization_id=:organization_id "
                    "AND idempotency_key='pg:forced-rollback'"
                ),
                {"organization_id": context.organization_id},
            )
            incomplete_snapshots = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM inventory_transaction_lines AS line
                    JOIN inventory_transactions AS tx ON tx.id = line.transaction_id
                    WHERE tx.organization_id = :organization_id
                      AND tx.status IN ('POSTED', 'REVERSED')
                      AND (
                          line.unit_cost_amount IS NULL
                          OR line.total_cost_amount IS NULL
                          OR line.quantity_after IS NULL
                          OR line.average_unit_cost_after IS NULL
                      )
                    """
                ),
                {"organization_id": context.organization_id},
            )
        assert ledger == await balance()
        assert failed_count == 0
        assert incomplete_snapshots == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_inventory_transfer_global_locking_and_outbox_atomicity(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, source_warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    destination_location_id = uuid4()
    destination_warehouse_id = uuid4()
    second_item_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO locations (
                        id, organization_id, name, timezone, address,
                        is_active, is_primary, created_at, updated_at
                    ) VALUES (
                        :location_id, :organization_id, 'Airport', 'Asia/Almaty', NULL,
                        true, false, now(), now()
                    )
                    """
                ),
                {
                    "location_id": destination_location_id,
                    "organization_id": context.organization_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO inventory_items (
                        id, organization_id, name, sku, base_unit, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :item_id, :organization_id, 'Milk', 'PG-MILK', 'g', true,
                        now(), now()
                    )
                    """
                ),
                {
                    "item_id": second_item_id,
                    "organization_id": context.organization_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO warehouses (
                        id, organization_id, location_id, name, is_active,
                        created_at, updated_at
                    ) VALUES (
                        :warehouse_id, :organization_id, :location_id,
                        'Airport Warehouse', true, now(), now()
                    )
                    """
                ),
                {
                    "warehouse_id": destination_warehouse_id,
                    "organization_id": context.organization_id,
                    "location_id": destination_location_id,
                },
            )

        async def inventory_service(session, sink=None):
            return InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
                sink or OutboxEventSink(OutboxRepository(session)),
            )

        async def operations_service(session, sink=None):
            event_sink = sink or OutboxEventSink(OutboxRepository(session))
            return InventoryOperationsService(
                SqlAlchemyInventoryOperationsRepository(session),
                await inventory_service(session, event_sink),
                event_sink,
            )

        async with sessions() as session:
            inventory = await inventory_service(session)
            for warehouse_id, unit_cost, key in (
                (source_warehouse_id, "8", "pg:transfer:source-opening"),
                (destination_warehouse_id, "10", "pg:transfer:destination-opening"),
            ):
                await inventory.create_and_post(
                    context,
                    CreateAndPostCommand(
                        context.organization_id,
                        context.user_id,
                        warehouse_id,
                        InventoryTransactionType.OPENING_BALANCE,
                        "Transfer opening",
                        (
                            QuantityInput(
                                item_id, Decimal("1000"), UnitCode.G, Decimal(unit_cost)
                            ),
                            QuantityInput(
                                second_item_id,
                                Decimal("1000"),
                                UnitCode.G,
                                Decimal(unit_cost),
                            ),
                        ),
                        key,
                    ),
                )

        async def create_transfer(source_id, destination_id, lines):
            async with sessions() as session:
                return await (await operations_service(session)).create_transfer(
                    context,
                    source_id,
                    destination_id,
                    datetime.now(UTC),
                    None,
                    tuple(
                        OperationLineInput(line_item_id, Decimal(quantity), UnitCode.G)
                        for line_item_id, quantity in lines
                    ),
                )

        transfer_a = await create_transfer(
            source_warehouse_id,
            destination_warehouse_id,
            ((item_id, "100"), (second_item_id, "200")),
        )
        transfer_b = await create_transfer(
            destination_warehouse_id,
            source_warehouse_id,
            ((second_item_id, "100"), (item_id, "50")),
        )

        async def post_transfer(transfer_id):
            async with sessions() as session:
                return await (await operations_service(session)).post_transfer(
                    context, transfer_id
                )

        posted_a, posted_b = await asyncio.gather(
            post_transfer(transfer_a.id), post_transfer(transfer_b.id)
        )
        assert posted_a.status.value == posted_b.status.value == "POSTED"

        async with sessions() as session:
            balances = dict(
                (
                    await session.execute(
                        text(
                            "SELECT warehouse_id, quantity FROM stock_balances "
                            "WHERE organization_id=:organization_id "
                            "AND inventory_item_id=:item_id"
                        ),
                        {
                            "organization_id": context.organization_id,
                            "item_id": item_id,
                        },
                    )
                ).all()
            )
            assert balances == {
                source_warehouse_id: Decimal("950.000000"),
                destination_warehouse_id: Decimal("1050.000000"),
            }
            second_balances = dict(
                (
                    await session.execute(
                        text(
                            "SELECT warehouse_id, quantity FROM stock_balances "
                            "WHERE organization_id=:organization_id "
                            "AND inventory_item_id=:item_id"
                        ),
                        {
                            "organization_id": context.organization_id,
                            "item_id": second_item_id,
                        },
                    )
                ).all()
            )
            assert second_balances == {
                source_warehouse_id: Decimal("900.000000"),
                destination_warehouse_id: Decimal("1100.000000"),
            }
            assert await session.scalar(
                select(func.count(OutboxEventModel.id)).where(
                    OutboxEventModel.event_name == "inventory.transfer_posted",
                    OutboxEventModel.organization_id == context.organization_id,
                )
            ) == 2

        failing = await create_transfer(
            source_warehouse_id, destination_warehouse_id, ((item_id, "10"),)
        )
        async with sessions() as session:
            failing_sink = OutboxEventSink(FailingOutboxRepository(session))
            with pytest.raises(RuntimeError, match="forced outbox failure"):
                await (await operations_service(session, failing_sink)).post_transfer(
                    context, failing.id
                )
        async with sessions() as session:
            status_and_transactions = (
                await session.execute(
                    text(
                        "SELECT status, out_transaction_id, in_transaction_id "
                        "FROM inventory_transfers WHERE id=:transfer_id"
                    ),
                    {"transfer_id": failing.id},
                )
            ).one()
            assert status_and_transactions == ("DRAFT", None, None)
            balances_after_failure = dict(
                (
                    await session.execute(
                        text(
                            "SELECT warehouse_id, quantity FROM stock_balances "
                            "WHERE organization_id=:organization_id "
                            "AND inventory_item_id=:item_id"
                        ),
                        {
                            "organization_id": context.organization_id,
                            "item_id": item_id,
                        },
                    )
                ).all()
            )
            assert balances_after_failure == balances
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_count_detects_net_zero_movement_during_snapshot(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    snapshot_started = asyncio.Event()
    release_snapshot = asyncio.Event()

    def inventory_service(session, sink=None):
        return InventoryService(
            SqlAlchemyInventoryRepository(session),
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
            sink or OutboxEventSink(OutboxRepository(session)),
        )

    try:
        async with sessions() as session:
            await inventory_service(session).create_and_post(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    warehouse_id,
                    InventoryTransactionType.OPENING_BALANCE,
                    "Count opening",
                    (QuantityInput(item_id, Decimal("1000"), UnitCode.G, Decimal("8")),),
                    "pg:count:opening",
                ),
            )

        async with sessions() as count_session:
            repository = SqlAlchemyInventoryOperationsRepository(count_session)
            original_snapshots = repository.count_snapshots

            async def delayed_snapshots(organization_id, target_warehouse_id, item_ids):
                snapshot_started.set()
                await release_snapshot.wait()
                return await original_snapshots(
                    organization_id, target_warehouse_id, item_ids
                )

            repository.count_snapshots = delayed_snapshots
            sink = OutboxEventSink(OutboxRepository(count_session))
            operations = InventoryOperationsService(
                repository, inventory_service(count_session, sink), sink
            )
            create_task = asyncio.create_task(
                operations.create_count(
                    context,
                    warehouse_id,
                    InventoryCountType.PARTIAL,
                    (item_id,),
                    "Snapshot race",
                )
            )
            await snapshot_started.wait()
            for quantity, key in (
                (Decimal("-100"), "pg:count:out"),
                (Decimal("100"), "pg:count:in"),
            ):
                async with sessions() as movement_session:
                    await inventory_service(movement_session).create_and_post(
                        context,
                        CreateAndPostCommand(
                            context.organization_id,
                            context.user_id,
                            warehouse_id,
                            InventoryTransactionType.ADJUSTMENT,
                            "Movement during count snapshot",
                            (QuantityInput(item_id, quantity, UnitCode.G),),
                            key,
                        ),
                    )
            release_snapshot.set()
            count = await create_task
            await operations.update_count_lines(
                context,
                count.id,
                (OperationLineInput(item_id, Decimal("1000"), UnitCode.G),),
                {},
            )
            with pytest.raises(InventoryCountChanged):
                await operations.post_count(context, count.id, False)
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_menu_recipe_and_default_variant_concurrency(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, _, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def service(session) -> MenuService:
        inventory = SqlAlchemyInventoryRepository(session)
        return MenuService(
            SqlAlchemyMenuRepository(session),
            MenuInventoryGateway(inventory),
            OrganizationService(SqlAlchemyOrganizationRepository(session)),
        )

    try:
        async with sessions() as session:
            menu = service(session)
            category = await menu.create_category(context, "Coffee", 0)
            product = await menu.create_product(
                context,
                category.id,
                "Concurrent Cappuccino",
                None,
                None,
                VariantInput("250 ml", None, 150000),
            )
            first_id = product.variants[0].id
            second = await menu.create_variant(
                context,
                product.id,
                VariantInput("350 ml", None, 180000),
                False,
                1,
            )

        async def update_variant(variant_id: UUID, *, name=None, is_default=None):
            async with sessions() as session:
                return await service(session).update_variant(
                    context,
                    variant_id,
                    name=name,
                    sku=None,
                    sku_set=False,
                    base_price_minor=None,
                    is_default=is_default,
                    sort_order=None,
                    status=None,
                )

        await asyncio.gather(
            update_variant(second.id, is_default=True),
            update_variant(second.id, name="350 ml renamed"),
        )
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM product_variants "
                        "WHERE product_id=:product_id AND status <> 'ARCHIVED' AND is_default"
                    ),
                    {"product_id": product.id},
                )
                == 1
            )

        async def archive(variant_id: UUID):
            async with sessions() as session:
                return await service(session).archive_variant(context, variant_id)

        archive_results = await asyncio.gather(
            archive(first_id), archive(second.id), return_exceptions=True
        )
        assert sum(not isinstance(value, Exception) for value in archive_results) == 1
        assert sum(isinstance(value, InvalidMenuOperation) for value in archive_results) == 1
        async with engine.connect() as connection:
            active, active_default = (
                await connection.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE status <> 'ARCHIVED'), "
                        "count(*) FILTER (WHERE status <> 'ARCHIVED' AND is_default) "
                        "FROM product_variants WHERE product_id=:product_id"
                    ),
                    {"product_id": product.id},
                )
            ).one()
            assert (active, active_default) == (1, 1)
            active_variant_id = await connection.scalar(
                text(
                    "SELECT id FROM product_variants "
                    "WHERE product_id=:product_id AND status <> 'ARCHIVED'"
                ),
                {"product_id": product.id},
            )

        async def replace_recipe(quantity: str):
            async with sessions() as session:
                return await service(session).set_recipe(
                    context,
                    active_variant_id,
                    "Concurrent recipe",
                    Decimal(1),
                    (RecipeComponentInput(item_id, Decimal(quantity), UnitCode.G, 0),),
                )

        await asyncio.gather(replace_recipe("18"), replace_recipe("20"))
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT component.quantity FROM recipe_components component "
                            "JOIN recipes recipe ON recipe.id=component.recipe_id "
                            "WHERE recipe.product_variant_id=:variant_id"
                        ),
                        {"variant_id": active_variant_id},
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0] in {Decimal("18.000000"), Decimal("20.000000")}

        async with engine.connect() as blocker:
            transaction = await blocker.begin()
            await blocker.execute(
                text("SELECT id FROM product_variants WHERE id=:id FOR UPDATE"),
                {"id": active_variant_id},
            )
            pending_recipe = asyncio.create_task(replace_recipe("22"))
            await asyncio.sleep(0.1)
            await blocker.execute(
                text("UPDATE product_variants SET status='ARCHIVED' WHERE id=:id"),
                {"id": active_variant_id},
            )
            await transaction.commit()
        with pytest.raises(InvalidMenuOperation, match="archived variant"):
            await pending_recipe

        async with sessions() as session:
            menu = service(session)
            lifecycle_category = await menu.create_category(context, "Lifecycle", 1)
            lifecycle_product = await menu.create_product(
                context,
                lifecycle_category.id,
                "Lifecycle product",
                None,
                None,
                VariantInput("Default", None, 10000),
            )

        async def archive_product():
            async with sessions() as session:
                return await service(session).archive_product(context, lifecycle_product.id)

        async def rename_product():
            async with sessions() as session:
                return await service(session).update_product(
                    context,
                    lifecycle_product.id,
                    category_id=None,
                    name="Renamed lifecycle product",
                    description=None,
                    description_set=False,
                    image_url=None,
                    image_url_set=False,
                    status=None,
                )

        await asyncio.gather(archive_product(), rename_product(), return_exceptions=True)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT status FROM products WHERE id=:id"),
                    {"id": lifecycle_product.id},
                )
                == "ARCHIVED"
            )

        async def archive_category():
            async with sessions() as session:
                return await service(session).archive_category(context, lifecycle_category.id)

        async def rename_category():
            async with sessions() as session:
                return await service(session).update_category(
                    context, lifecycle_category.id, name="Renamed lifecycle", sort_order=None
                )

        await asyncio.gather(archive_category(), rename_category(), return_exceptions=True)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT is_active FROM menu_categories WHERE id=:id"),
                    {"id": lifecycle_category.id},
                )
                is False
            )

        async with sessions() as session:
            menu = service(session)
            modifier_category = await menu.create_category(context, "Modifiers", 2)
            modifier_product = await menu.create_product(
                context,
                modifier_category.id,
                "Modifier concurrency",
                None,
                None,
                VariantInput("Default", None, 10000),
            )
            modifier_variant_id = modifier_product.variants[0].id
            modifier_group = await menu.create_modifier_group(
                context,
                modifier_variant_id,
                "Extras",
                ModifierSelectionType.MULTIPLE,
                0,
                2,
                0,
            )
            modifier_option = await menu.create_modifier_option(
                context, modifier_group.id, "Extra coffee", 5000, False, 0
            )

        async def replace_modifier(quantity: str):
            async with sessions() as session:
                return await service(session).replace_modifier_components(
                    context,
                    modifier_option.id,
                    (
                        ModifierComponentInput(
                            item_id, Decimal(quantity), UnitCode.G, 0
                        ),
                    ),
                )

        await asyncio.gather(replace_modifier("18"), replace_modifier("20"))
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT quantity_delta FROM modifier_option_components "
                        "WHERE modifier_option_id=:option_id"
                    ),
                    {"option_id": modifier_option.id},
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0] in {Decimal("18.000000"), Decimal("20.000000")}

        async with engine.connect() as blocker:
            transaction = await blocker.begin()
            await blocker.execute(
                text("SELECT id FROM modifier_groups WHERE id=:id FOR UPDATE"),
                {"id": modifier_group.id},
            )
            pending_replacement = asyncio.create_task(replace_modifier("22"))
            await asyncio.sleep(0.1)
            await blocker.execute(
                text("UPDATE modifier_groups SET is_active=false WHERE id=:id"),
                {"id": modifier_group.id},
            )
            await transaction.commit()
        with pytest.raises(InvalidMenuOperation, match="Archived modifier groups"):
            await pending_replacement
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM modifier_option_components "
                        "WHERE modifier_option_id=:option_id"
                    ),
                    {"option_id": modifier_option.id},
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_sales_idempotency_totals_shift_races_and_no_posting(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as connection:
        location_id = await connection.scalar(
            text("SELECT location_id FROM warehouses WHERE id=:warehouse_id"),
            {"warehouse_id": warehouse_id},
        )

    try:
        async with sessions() as session:
            inventory = SqlAlchemyInventoryRepository(session)
            organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
            menu = MenuService(
                SqlAlchemyMenuRepository(session),
                MenuInventoryGateway(inventory),
                organizations,
            )
            category = await menu.create_category(context, "Sales", 0)
            product = await menu.create_product(
                context,
                category.id,
                "Concurrent item",
                None,
                None,
                VariantInput("Default", None, 10000),
            )
            variant_id = product.variants[0].id

        class StaticMenu:
            async def resolve_order_item(self, *args, **kwargs):
                return SellableItemSnapshot(
                    product.id,
                    "Concurrent item",
                    variant_id,
                    "Default",
                    10000,
                    5000,
                    15000,
                    (),
                    (
                        SellableComponentSnapshot(
                            item_id, "Coffee", UnitCode.G, Decimal("18")
                        ),
                    ),
                )

        def services(session):
            repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
            return (
                RegisterService(repository, organizations),
                ShiftService(
                    repository,
                    organizations,
                    InventorySalesGateway(SqlAlchemyInventoryRepository(session)),
                ),
                OrderService(repository, organizations, StaticMenu()),
            )

        async with sessions() as session:
            register_service, _, _ = services(session)
            register = await register_service.create(context, location_id, "Concurrent")

        async def open_shift():
            async with sessions() as session:
                _, shift_service, _ = services(session)
                return await shift_service.open(context, register.id, warehouse_id)

        opened = await asyncio.gather(open_shift(), open_shift(), return_exceptions=True)
        assert sum(not isinstance(value, Exception) for value in opened) == 1
        assert sum(isinstance(value, Exception) for value in opened) == 1
        shift = next(value for value in opened if not isinstance(value, Exception))
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM register_shifts "
                        "WHERE register_id=:register_id AND status='OPEN'"
                    ),
                    {"register_id": register.id},
                )
                == 1
            )

        client_order_id = uuid4()

        async def create_order(client_id=client_order_id, shift_id=shift.id):
            async with sessions() as session:
                _, _, order_service = services(session)
                return await order_service.create(
                    context,
                    CreateOrderInput(
                        client_id,
                        shift_id,
                        OrderType.TAKEAWAY,
                        None,
                        None,
                        None,
                    ),
                )

        async with sessions() as session:
            register_service, shift_service, _ = services(session)
            second_register = await register_service.create(
                context, location_id, "Second concurrent"
            )
            second_shift = await shift_service.open(
                context, second_register.id, warehouse_id
            )
        cross_shift_client_id = uuid4()
        cross_shift_orders = await asyncio.gather(
            create_order(cross_shift_client_id, shift.id),
            create_order(cross_shift_client_id, second_shift.id),
        )
        assert cross_shift_orders[0].id == cross_shift_orders[1].id
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM sales_orders "
                        "WHERE organization_id=:organization_id "
                        "AND client_order_id=:client_order_id"
                    ),
                    {
                        "organization_id": context.organization_id,
                        "client_order_id": cross_shift_client_id,
                    },
                )
                == 1
            )

        duplicate_orders = await asyncio.gather(
            *(create_order() for _ in range(10))
        )
        assert len({value.id for value in duplicate_orders}) == 1
        order = duplicate_orders[0]
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM sales_orders "
                        "WHERE organization_id=:organization_id "
                        "AND client_order_id=:client_order_id"
                    ),
                    {
                        "organization_id": context.organization_id,
                        "client_order_id": client_order_id,
                    },
                )
                == 1
            )

        async def add_item(client_item_id):
            async with sessions() as session:
                _, _, order_service = services(session)
                return await order_service.add_item(
                    context,
                    order.id,
                    AddOrderItemInput(client_item_id, variant_id, (), 1, None),
                )

        distinct_ids = [uuid4() for _ in range(10)]
        await asyncio.gather(*(add_item(value) for value in distinct_ids))
        duplicate_item_id = uuid4()
        duplicates = await asyncio.gather(
            *(add_item(duplicate_item_id) for _ in range(10))
        )
        assert len({value.id for value in duplicates}) == 1
        async with engine.connect() as connection:
            line_count, total = (
                await connection.execute(
                    text(
                        "SELECT count(item.id), orders.total_minor "
                        "FROM sales_orders orders "
                        "JOIN sales_order_items item ON item.order_id=orders.id "
                        "WHERE orders.id=:order_id GROUP BY orders.total_minor"
                    ),
                    {"order_id": order.id},
                )
            ).one()
            duplicate_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM sales_order_items "
                    "WHERE order_id=:order_id AND client_item_id=:client_item_id"
                ),
                {"order_id": order.id, "client_item_id": duplicate_item_id},
            )
            assert (line_count, total, duplicate_count) == (11, 165000, 1)

        async with sessions() as session:
            register_service, shift_service, _ = services(session)
            race_register = await register_service.create(context, location_id, "Shift race")
            race_shift = await shift_service.open(context, race_register.id, warehouse_id)

        async def close_race_shift():
            async with sessions() as session:
                _, shift_service, _ = services(session)
                return await shift_service.close(context, race_shift.id)

        raced = await asyncio.gather(
            create_order(uuid4(), race_shift.id),
            close_race_shift(),
            return_exceptions=True,
        )
        assert sum(not isinstance(value, Exception) for value in raced) == 1
        async with engine.connect() as connection:
            race_status = await connection.scalar(
                text("SELECT status FROM register_shifts WHERE id=:shift_id"),
                {"shift_id": race_shift.id},
            )
            race_orders = await connection.scalar(
                text("SELECT count(*) FROM sales_orders WHERE shift_id=:shift_id"),
                {"shift_id": race_shift.id},
            )
            assert (race_status, race_orders) in {("CLOSED", 0), ("OPEN", 1)}
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM inventory_transactions WHERE type='SALE'")
                )
                == 0
            )
            assert await connection.scalar(text("SELECT count(*) FROM payments")) == 0
            absent_tables = (
                await connection.execute(
                    text(
                        "SELECT to_regclass(name) FROM unnest(ARRAY["
                        "'payment_transactions','revenues','cogs_entries']) AS name"
                    )
                )
            ).scalars().all()
            assert absent_tables == [None, None, None]
            assert await connection.scalar(text("SELECT count(*) FROM finance_entries")) == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_payments_atomicity_concurrency_and_sale_posting(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as connection:
        location_id = await connection.scalar(
            text("SELECT location_id FROM warehouses WHERE id=:warehouse_id"),
            {"warehouse_id": warehouse_id},
        )

    try:
        async with sessions() as session:
            inventory = SqlAlchemyInventoryRepository(session)
            organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
            menu = MenuService(
                SqlAlchemyMenuRepository(session),
                MenuInventoryGateway(inventory),
                organizations,
            )
            category = await menu.create_category(context, "Payments", 0)
            product = await menu.create_product(
                context,
                category.id,
                "Settlement item",
                None,
                None,
                VariantInput("Default", None, 670000),
            )
            variant_id = product.variants[0].id

        class StaticMenu:
            def __init__(self, total_minor: int) -> None:
                self.total_minor = total_minor

            async def resolve_order_item(self, *args, **kwargs):
                return SellableItemSnapshot(
                    product.id,
                    "Settlement item",
                    variant_id,
                    "Default",
                    self.total_minor,
                    0,
                    self.total_minor,
                    (),
                    (
                        SellableComponentSnapshot(
                            item_id, "Coffee", UnitCode.G, Decimal("18")
                        ),
                    ),
                )

        def sales_services(session):
            repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
            return (
                RegisterService(repository, organizations),
                ShiftService(
                    repository,
                    organizations,
                    InventorySalesGateway(SqlAlchemyInventoryRepository(session)),
                ),
            )

        async with sessions() as session:
            register_service, shift_service = sales_services(session)
            register = await register_service.create(context, location_id, "Payments")
            shift = await shift_service.open(context, register.id, warehouse_id)

        async def new_order(
            total_minor: int = 670000, *, target_shift_id: UUID = shift.id
        ):
            async with sessions() as session:
                repository = SqlAlchemySalesRepository(session)
                service = OrderService(
                    repository,
                    OrganizationService(SqlAlchemyOrganizationRepository(session)),
                    StaticMenu(total_minor),
                )
                created = await service.create(
                    context,
                    CreateOrderInput(
                        uuid4(),
                        target_shift_id,
                        OrderType.TAKEAWAY,
                        None,
                        None,
                        None,
                    ),
                )
                return await service.add_item(
                    context,
                    created.id,
                    AddOrderItemInput(uuid4(), variant_id, (), 1, None),
                )

        def payment_service(
            session, *, repository=None, gateway=None, inventory=None, sink=None
        ):
            sales_repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
            inventory_service = InventoryService(
                SqlAlchemyInventoryRepository(session),
                organizations,
                reference_validator=SalesOrderReferenceValidator(sales_repository),
            )
            return PaymentService(
                repository or SqlAlchemyPaymentRepository(session),
                gateway or SalesSettlementGateway(sales_repository, organizations),
                inventory or InventorySaleGateway(inventory_service),
                sink or OutboxEventSink(OutboxRepository(session)),
            )

        async with sessions() as session:
            await InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            ).create_and_post(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    warehouse_id,
                    InventoryTransactionType.OPENING_BALANCE,
                    "Payment test cost basis",
                    (QuantityInput(item_id, Decimal("1000"), UnitCode.G, Decimal("8")),),
                    "payments:opening-balance",
                ),
            )

        payment_input = CompletePaymentInput(
            uuid4(),
            (
                PaymentLineInput(PaymentMethod.CASH, 200000, 250000, "drawer"),
                PaymentLineInput(PaymentMethod.CARD, 470000, None, "terminal"),
            ),
        )
        concurrent_order = await new_order()

        async def pay(order_id, value=payment_input):
            async with sessions() as session:
                return await payment_service(session).complete(context, order_id, value)

        repeated = await asyncio.gather(
            *(pay(concurrent_order.id) for _ in range(10))
        )
        assert len({payment.id for payment in repeated}) == 1
        payment = repeated[0]
        assert payment.amount_minor == 670000
        assert [line.method for line in payment.lines] == [
            PaymentMethod.CASH,
            PaymentMethod.CARD,
        ]
        assert payment.lines[0].change_minor == 50000
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT count(*) FROM payments WHERE order_id=:order_id"),
                {"order_id": concurrent_order.id},
            ) == 1
            paid = (
                await connection.execute(
                    text(
                        "SELECT status, paid_by_user_id, paid_at, "
                        "inventory_transaction_id, cogs_amount, cogs_status "
                        "FROM sales_orders "
                        "WHERE id=:order_id"
                    ),
                    {"order_id": concurrent_order.id},
                )
            ).one()
            assert paid.status == "PAID"
            assert paid.paid_by_user_id == context.user_id
            assert paid.paid_at is not None
            assert paid.inventory_transaction_id is not None
            assert paid.cogs_amount == Decimal("144.000000")
            assert paid.cogs_status == "COMPLETE"
            sale = (
                await connection.execute(
                    text(
                        "SELECT tx.type, tx.status, tx.warehouse_id, "
                        "tx.reference_type, tx.reference_id, tx.idempotency_key, "
                        "line.quantity_delta, line.unit_cost_amount, "
                        "line.total_cost_amount FROM inventory_transactions tx "
                        "JOIN inventory_transaction_lines line "
                        "ON line.transaction_id=tx.id "
                        "WHERE tx.id=:transaction_id"
                    ),
                    {"transaction_id": paid.inventory_transaction_id},
                )
            ).one()
            assert sale == (
                "SALE",
                "POSTED",
                warehouse_id,
                "ORDER",
                concurrent_order.id,
                f"sale:order:{concurrent_order.id}",
                Decimal("-18.000000"),
                Decimal("8.000000"),
                Decimal("-144.000000"),
            )
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("982.000000")
            outbox = (
                await connection.execute(
                    text(
                        "SELECT event_name, event_version, aggregate_id, payload, "
                        "processed_at FROM outbox_events "
                        "WHERE organization_id=:organization_id "
                        "ORDER BY event_name"
                    ),
                    {
                        "organization_id": context.organization_id,
                    },
                )
            ).all()
            assert [(row.event_name, row.event_version) for row in outbox] == [
                ("inventory.cost_updated", 1),
                ("inventory.transaction_posted", 1),
                ("inventory.valuation_changed", 1),
                ("payment.completed", 1),
            ]
            assert all(row.processed_at is None for row in outbox)
            assert next(
                row for row in outbox if row.event_name == "payment.completed"
            ).aggregate_id == payment.id
            assert {
                row.aggregate_id
                for row in outbox
                if row.event_name
                in {
                    "inventory.transaction_posted",
                    "inventory.valuation_changed",
                }
            } == {paid.inventory_transaction_id}
            payment_event = next(
                row for row in outbox if row.event_name == "payment.completed"
            )
            assert payment_event.payload == {
                "payment_id": str(payment.id),
                "order_id": str(concurrent_order.id),
                "organization_id": str(context.organization_id),
                "location_id": str(location_id),
                "amount_minor": 670000,
            }

        cross_order = await new_order()
        with pytest.raises(PaymentIdempotencyConflict):
            await pay(cross_order.id)
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT status FROM sales_orders WHERE id=:order_id"),
                {"order_id": cross_order.id},
            ) == "OPEN"

        double_order = await new_order()
        different_keys = (
            CompletePaymentInput(
                uuid4(), (PaymentLineInput(PaymentMethod.CARD, 670000),)
            ),
            CompletePaymentInput(
                uuid4(), (PaymentLineInput(PaymentMethod.OTHER, 670000),)
            ),
        )
        doubled = await asyncio.gather(
            *(pay(double_order.id, value) for value in different_keys),
            return_exceptions=True,
        )
        assert sum(not isinstance(value, Exception) for value in doubled) == 1
        assert sum(isinstance(value, OrderAlreadyPaid) for value in doubled) == 1

        outbox_failure_order = await new_order()
        async with sessions() as session:
            with pytest.raises(RuntimeError, match="forced outbox failure"):
                await payment_service(
                    session,
                    sink=OutboxEventSink(FailingOutboxRepository(session)),
                ).complete(
                    context,
                    outbox_failure_order.id,
                    CompletePaymentInput(
                        uuid4(),
                        (PaymentLineInput(PaymentMethod.CARD, 670000),),
                    ),
                )
        async with engine.connect() as connection:
            assert (
                await connection.execute(
                    text(
                        "SELECT orders.status, count(payments.id) "
                        "FROM sales_orders orders LEFT JOIN payments "
                        "ON payments.order_id=orders.id WHERE orders.id=:order_id "
                        "GROUP BY orders.status"
                    ),
                    {"order_id": outbox_failure_order.id},
                )
            ).one() == ("OPEN", 0)
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions "
                    "WHERE type='SALE' AND reference_id=:order_id"
                ),
                {"order_id": outbox_failure_order.id},
            ) == 0
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE payload->>'order_id'=:order_id"
                ),
                {"order_id": str(outbox_failure_order.id)},
            ) == 0
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("964.000000")

        class FailingInventoryGateway(InventorySaleGateway):
            async def stage_sale(self, *args, **kwargs):
                await super().stage_sale(*args, **kwargs)
                raise RuntimeError("forced inventory failure")

        inventory_failure_order = await new_order()
        async with engine.connect() as connection:
            balance_before_inventory_failure = await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            )
        async with sessions() as session:
            sales_repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(
                SqlAlchemyOrganizationRepository(session)
            )
            failing_inventory = FailingInventoryGateway(
                InventoryService(
                    SqlAlchemyInventoryRepository(session),
                    organizations,
                    reference_validator=SalesOrderReferenceValidator(
                        sales_repository
                    ),
                )
            )
            with pytest.raises(RuntimeError, match="forced inventory failure"):
                await payment_service(
                    session, inventory=failing_inventory
                ).complete(
                    context,
                    inventory_failure_order.id,
                    CompletePaymentInput(
                        uuid4(),
                        (PaymentLineInput(PaymentMethod.CARD, 670000),),
                    ),
                )
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT status FROM sales_orders WHERE id=:order_id"),
                {"order_id": inventory_failure_order.id},
            ) == "OPEN"
            assert await connection.scalar(
                text("SELECT count(*) FROM payments WHERE order_id=:order_id"),
                {"order_id": inventory_failure_order.id},
            ) == 0
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions "
                    "WHERE type='SALE' AND reference_id=:order_id"
                ),
                {"order_id": inventory_failure_order.id},
            ) == 0
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == balance_before_inventory_failure

        class FailingPaymentRepository(SqlAlchemyPaymentRepository):
            async def add(self, value):
                await super().add(value)
                raise RuntimeError("forced payment failure")

        payment_failure_order = await new_order()
        async with sessions() as session:
            with pytest.raises(RuntimeError, match="forced payment failure"):
                await payment_service(
                    session,
                    repository=FailingPaymentRepository(session),
                ).complete(
                    context,
                    payment_failure_order.id,
                    CompletePaymentInput(
                        uuid4(), (PaymentLineInput(PaymentMethod.CARD, 670000),)
                    ),
                )

        class FailingSalesGateway(SalesSettlementGateway):
            async def mark_order_paid(
                self,
                order_id,
                paid_by_user_id,
                paid_at,
                inventory_transaction_id,
                cogs_amount,
                cogs_status,
            ):
                await super().mark_order_paid(
                    order_id,
                    paid_by_user_id,
                    paid_at,
                    inventory_transaction_id,
                    cogs_amount,
                    cogs_status,
                )
                raise RuntimeError("forced order failure")

        order_failure_order = await new_order()
        async with sessions() as session:
            sales_repository = SqlAlchemySalesRepository(session)
            failing_gateway = FailingSalesGateway(
                sales_repository,
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            )
            with pytest.raises(RuntimeError, match="forced order failure"):
                await payment_service(session, gateway=failing_gateway).complete(
                    context,
                    order_failure_order.id,
                    CompletePaymentInput(
                        uuid4(), (PaymentLineInput(PaymentMethod.CARD, 670000),)
                    ),
                )
        async with engine.connect() as connection:
            for order_id in (payment_failure_order.id, order_failure_order.id):
                status_value, payment_count = (
                    await connection.execute(
                        text(
                            "SELECT orders.status, count(payments.id) "
                            "FROM sales_orders orders LEFT JOIN payments "
                            "ON payments.order_id=orders.id WHERE orders.id=:order_id "
                            "GROUP BY orders.status"
                        ),
                        {"order_id": order_id},
                    )
                ).one()
                assert (status_value, payment_count) == ("OPEN", 0)
                assert await connection.scalar(
                    text(
                        "SELECT count(*) FROM inventory_transactions "
                        "WHERE type='SALE' AND reference_id=:order_id"
                    ),
                    {"order_id": order_id},
                ) == 0
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("964.000000")

        cancel_race_order = await new_order()

        async def cancel_order():
            async with sessions() as session:
                return await OrderService(
                    SqlAlchemySalesRepository(session),
                    OrganizationService(SqlAlchemyOrganizationRepository(session)),
                    StaticMenu(670000),
                ).cancel(context, cancel_race_order.id, "Race")

        raced = await asyncio.gather(
            pay(
                cancel_race_order.id,
                CompletePaymentInput(
                    uuid4(), (PaymentLineInput(PaymentMethod.CARD, 670000),)
                ),
            ),
            cancel_order(),
            return_exceptions=True,
        )
        assert sum(not isinstance(value, Exception) for value in raced) == 1
        async with engine.connect() as connection:
            state = (
                await connection.execute(
                    text(
                        "SELECT orders.status, count(payments.id) "
                        "FROM sales_orders orders LEFT JOIN payments "
                        "ON payments.order_id=orders.id WHERE orders.id=:order_id "
                        "GROUP BY orders.status"
                    ),
                    {"order_id": cancel_race_order.id},
                )
            ).one()
            assert state in {("PAID", 1), ("CANCELLED", 0)}

        async with sessions() as session:
            register_service, shift_service = sales_services(session)
            close_register = await register_service.create(
                context, location_id, "Payment close race"
            )
            close_shift = await shift_service.open(
                context, close_register.id, warehouse_id
            )
        close_race_order = await new_order(target_shift_id=close_shift.id)

        async def close_shift_once():
            async with sessions() as session:
                _, shift_service = sales_services(session)
                return await shift_service.close(context, close_shift.id)

        payment_result, close_result = await asyncio.gather(
            pay(
                close_race_order.id,
                CompletePaymentInput(
                    uuid4(), (PaymentLineInput(PaymentMethod.CARD, 670000),)
                ),
            ),
            close_shift_once(),
            return_exceptions=True,
        )
        assert not isinstance(payment_result, Exception)
        assert not isinstance(close_result, Exception) or isinstance(
            close_result, ShiftHasOpenOrders
        )
        if isinstance(close_result, Exception):
            assert not isinstance(await close_shift_once(), Exception)

        invalid_lines = (
            ("CASH", 10, 9, 0),
            ("CARD", 10, 10, 0),
            ("OTHER", 10, None, 1),
        )
        for method, amount, received, change in invalid_lines:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(IntegrityError):
                    await connection.execute(
                        text(
                            "INSERT INTO payment_lines "
                            "(id, payment_id, method, amount_minor, "
                            "cash_received_minor, change_minor, reference, "
                            "sort_order, created_at) VALUES "
                            "(:id, :payment_id, :method, :amount, :received, "
                            ":change, NULL, 99, now())"
                        ),
                        {
                            "id": uuid4(),
                            "payment_id": payment.id,
                            "method": method,
                            "amount": amount,
                            "received": received,
                            "change": change,
                        },
                    )
                await transaction.rollback()

        async with engine.connect() as connection:
            sale_count = await connection.scalar(
                text("SELECT count(*) FROM inventory_transactions WHERE type='SALE'")
            )
            assert sale_count == await connection.scalar(
                text("SELECT count(*) FROM payments")
            )
            assert sale_count == await connection.scalar(
                text(
                    "SELECT count(*) FROM sales_orders "
                    "WHERE status='PAID' AND inventory_transaction_id IS NOT NULL"
                )
            )
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM inventory_transaction_lines line "
                    "JOIN inventory_transactions tx ON tx.id=line.transaction_id "
                    "WHERE tx.type='SALE' AND line.quantity_delta >= 0"
                )
            ) == 0
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM (SELECT reference_id FROM "
                    "inventory_transactions WHERE type='SALE' "
                    "GROUP BY reference_id HAVING count(*) <> 1) duplicates"
                )
            ) == 0
            assert await connection.scalar(
                text("SELECT count(*) FROM outbox_events")
            ) == sale_count * 4
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE processed_at IS NOT NULL OR dead_lettered_at IS NOT NULL"
                )
            ) == 0
            finance_tables = (
                await connection.execute(
                    text(
                        "SELECT to_regclass(name) FROM unnest(ARRAY["
                        "'revenues','revenue_entries','cogs_entries']) "
                        "AS name"
                    )
                )
            ).scalars().all()
            assert finance_tables == [None, None, None]
            assert await connection.scalar(text("SELECT count(*) FROM finance_entries")) == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_sale_uses_modifier_recipe_snapshots_current_wac_and_edge_cases(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, coffee_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    item_specs = {
        "milk": (uuid4(), "Regular milk", "ml"),
        "oat": (uuid4(), "Oat milk", "ml"),
        "cup": (uuid4(), "Cup", "pcs"),
        "lid": (uuid4(), "Lid", "pcs"),
        "scarce": (uuid4(), "Scarce coffee", "g"),
        "zero": (uuid4(), "Free sample", "pcs"),
        "archived": (uuid4(), "Archived garnish", "pcs"),
        "missing": (uuid4(), "New syrup", "ml"),
    }

    try:
        async with engine.begin() as connection:
            location_id = await connection.scalar(
                text("SELECT location_id FROM warehouses WHERE id=:warehouse_id"),
                {"warehouse_id": warehouse_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO inventory_items "
                    "(id, organization_id, name, sku, base_unit, is_active, "
                    "created_at, updated_at) VALUES "
                    "(:id, :organization_id, :name, NULL, :unit, true, now(), now())"
                ),
                [
                    {
                        "id": item_id,
                        "organization_id": context.organization_id,
                        "name": name,
                        "unit": unit,
                    }
                    for item_id, name, unit in item_specs.values()
                ],
            )

        async with sessions() as session:
            organizations = OrganizationService(
                SqlAlchemyOrganizationRepository(session)
            )
            inventory = InventoryService(
                SqlAlchemyInventoryRepository(session), organizations
            )
            await inventory.create_and_post(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    warehouse_id,
                    InventoryTransactionType.OPENING_BALANCE,
                    "Stage 12 cost basis",
                    (
                        QuantityInput(coffee_id, Decimal("1000"), UnitCode.G, Decimal("8")),
                        QuantityInput(
                            item_specs["milk"][0], Decimal("10000"), UnitCode.ML, Decimal("0.7")
                        ),
                        QuantityInput(
                            item_specs["oat"][0], Decimal("10000"), UnitCode.ML, Decimal("1.2")
                        ),
                        QuantityInput(
                            item_specs["cup"][0], Decimal("100"), UnitCode.PCS, Decimal("35")
                        ),
                        QuantityInput(
                            item_specs["lid"][0], Decimal("100"), UnitCode.PCS, Decimal("15")
                        ),
                        QuantityInput(
                            item_specs["scarce"][0], Decimal("10"), UnitCode.G, Decimal("8")
                        ),
                        QuantityInput(
                            item_specs["zero"][0], Decimal("10"), UnitCode.PCS, Decimal("0")
                        ),
                        QuantityInput(
                            item_specs["archived"][0], Decimal("100"), UnitCode.PCS, Decimal("2")
                        ),
                    ),
                    "sale-posting:opening",
                ),
            )
            menu_service = MenuService(
                SqlAlchemyMenuRepository(session),
                MenuInventoryGateway(SqlAlchemyInventoryRepository(session)),
                organizations,
            )
            category = await menu_service.create_category(context, "Sale snapshots", 0)
            product = await menu_service.create_product(
                context,
                category.id,
                "Snapshot product",
                None,
                None,
                VariantInput("Default", None, 100000),
            )
            variant_id = product.variants[0].id

        class MutableMenu:
            def __init__(self) -> None:
                self.components = ()
                self.calls = 0

            async def resolve_order_item(self, *args, **kwargs):
                self.calls += 1
                return SellableItemSnapshot(
                    product.id,
                    "Snapshot product",
                    variant_id,
                    "Default",
                    100000,
                    0,
                    100000,
                    (),
                    self.components,
                )

        menu = MutableMenu()

        def component(item_id: UUID, name: str, unit: UnitCode, quantity: str):
            return SellableComponentSnapshot(item_id, name, unit, Decimal(quantity))

        async with sessions() as session:
            repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(
                SqlAlchemyOrganizationRepository(session)
            )
            register = await RegisterService(repository, organizations).create(
                context, location_id, "Sale snapshots"
            )
            shift = await ShiftService(
                repository,
                organizations,
                InventorySalesGateway(SqlAlchemyInventoryRepository(session)),
            ).open(context, register.id, warehouse_id)

        async def new_order(
            snapshots: tuple[tuple[SellableComponentSnapshot, ...], ...],
            quantities: tuple[int, ...] | None = None,
        ):
            quantities = quantities or tuple(1 for _ in snapshots)
            async with sessions() as session:
                service = OrderService(
                    SqlAlchemySalesRepository(session),
                    OrganizationService(SqlAlchemyOrganizationRepository(session)),
                    menu,
                )
                order = await service.create(
                    context,
                    CreateOrderInput(
                        uuid4(), shift.id, OrderType.TAKEAWAY, None, None, None
                    ),
                )
                for snapshot, quantity in zip(snapshots, quantities, strict=True):
                    menu.components = snapshot
                    order = await service.add_item(
                        context,
                        order.id,
                        AddOrderItemInput(
                            uuid4(), variant_id, (), quantity, None
                        ),
                    )
                return order

        def checkout(session):
            sales_repository = SqlAlchemySalesRepository(session)
            organizations = OrganizationService(
                SqlAlchemyOrganizationRepository(session)
            )
            inventory = InventoryService(
                SqlAlchemyInventoryRepository(session),
                organizations,
                reference_validator=SalesOrderReferenceValidator(
                    sales_repository
                ),
            )
            return PaymentService(
                SqlAlchemyPaymentRepository(session),
                SalesSettlementGateway(sales_repository, organizations),
                InventorySaleGateway(inventory),
            )

        async def pay(order):
            async with sessions() as session:
                return await checkout(session).complete(
                    context,
                    order.id,
                    CompletePaymentInput(
                        uuid4(),
                        (
                            PaymentLineInput(
                                PaymentMethod.CARD, order.total_minor
                            ),
                        ),
                    ),
                )

        modified_cappuccino = (
            component(coffee_id, "Coffee", UnitCode.G, "36"),
            component(item_specs["oat"][0], "Oat milk", UnitCode.ML, "230"),
            component(item_specs["cup"][0], "Cup", UnitCode.PCS, "1"),
            component(item_specs["lid"][0], "Lid", UnitCode.PCS, "1"),
        )
        espresso = (component(coffee_id, "Coffee", UnitCode.G, "18"),)
        snapshot_order = await new_order(
            (modified_cappuccino, espresso), (2, 1)
        )
        calls_at_order_creation = menu.calls
        menu.components = (
            component(coffee_id, "Changed coffee recipe", UnitCode.G, "20"),
            component(item_specs["milk"][0], "Regular milk", UnitCode.ML, "230"),
        )
        async with sessions() as session:
            await InventoryService(
                SqlAlchemyInventoryRepository(session),
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            ).create_and_post(
                context,
                CreateAndPostCommand(
                    context.organization_id,
                    context.user_id,
                    warehouse_id,
                    InventoryTransactionType.PURCHASE,
                    "WAC changed after order",
                    (
                        QuantityInput(
                            coffee_id,
                            Decimal("1000"),
                            UnitCode.G,
                            total_cost_amount=Decimal("10000"),
                        ),
                    ),
                    "sale-posting:wac-change",
                ),
            )
        await pay(snapshot_order)
        assert menu.calls == calls_at_order_creation

        async with engine.connect() as connection:
            order_state = (
                await connection.execute(
                    text(
                        "SELECT inventory_transaction_id, cogs_amount, cogs_status "
                        "FROM sales_orders WHERE id=:order_id"
                    ),
                    {"order_id": snapshot_order.id},
                )
            ).one()
            assert order_state.cogs_amount == Decimal("1462.000000")
            assert order_state.cogs_status == "COMPLETE"
            lines = (
                await connection.execute(
                    text(
                        "SELECT inventory_item_id, quantity_delta, unit_cost_amount "
                        "FROM inventory_transaction_lines "
                        "WHERE transaction_id=:transaction_id "
                        "ORDER BY inventory_item_id"
                    ),
                    {"transaction_id": order_state.inventory_transaction_id},
                )
            ).all()
            assert {item_id: (quantity, cost) for item_id, quantity, cost in lines} == {
                coffee_id: (Decimal("-90.000000"), Decimal("9.000000")),
                item_specs["oat"][0]: (
                    Decimal("-460.000000"),
                    Decimal("1.200000"),
                ),
                item_specs["cup"][0]: (
                    Decimal("-2.000000"),
                    Decimal("35.000000"),
                ),
                item_specs["lid"][0]: (
                    Decimal("-2.000000"),
                    Decimal("15.000000"),
                ),
            }
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances WHERE warehouse_id=:warehouse_id "
                    "AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": coffee_id},
            ) == Decimal("1910.000000")
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances WHERE warehouse_id=:warehouse_id "
                    "AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_specs["milk"][0]},
            ) == Decimal("10000.000000")

        negative_order = await new_order(
            ((component(item_specs["scarce"][0], "Scarce", UnitCode.G, "18"),),)
        )
        missing_order = await new_order(
            ((component(item_specs["missing"][0], "Syrup", UnitCode.ML, "20"),),)
        )
        zero_order = await new_order(
            ((component(item_specs["zero"][0], "Free", UnitCode.PCS, "1"),),)
        )
        inactive_order = await new_order(
            ((component(item_specs["archived"][0], "Archived", UnitCode.PCS, "1"),),)
        )
        empty_order = await new_order(((),))
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE inventory_items SET is_active=false WHERE id=:item_id"),
                {"item_id": item_specs["archived"][0]},
            )

        for order in (
            negative_order,
            missing_order,
            zero_order,
            inactive_order,
            empty_order,
        ):
            await pay(order)

        async with engine.connect() as connection:
            states = {
                row.id: row
                for row in (
                    await connection.execute(
                        text(
                            "SELECT id, inventory_transaction_id, cogs_amount, cogs_status "
                            "FROM sales_orders WHERE id = ANY(:order_ids)"
                        ),
                        {
                            "order_ids": [
                                negative_order.id,
                                missing_order.id,
                                zero_order.id,
                                inactive_order.id,
                                empty_order.id,
                            ]
                        },
                    )
                ).all()
            }
            assert (
                states[negative_order.id].cogs_amount,
                states[negative_order.id].cogs_status,
            ) == (Decimal("144.000000"), "COMPLETE")
            assert (
                states[missing_order.id].cogs_amount,
                states[missing_order.id].cogs_status,
            ) == (Decimal("0.000000"), "INCOMPLETE")
            assert (
                states[zero_order.id].cogs_amount,
                states[zero_order.id].cogs_status,
            ) == (Decimal("0.000000"), "COMPLETE")
            assert (
                states[inactive_order.id].cogs_amount,
                states[inactive_order.id].cogs_status,
            ) == (Decimal("2.000000"), "COMPLETE")
            assert states[empty_order.id].inventory_transaction_id is None
            assert (
                states[empty_order.id].cogs_amount,
                states[empty_order.id].cogs_status,
            ) == (Decimal("0.000000"), "COMPLETE")
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions "
                    "WHERE type='SALE' AND reference_id=:order_id"
                ),
                {"order_id": empty_order.id},
            ) == 0
            for item_id, expected in (
                (item_specs["scarce"][0], Decimal("-8.000000")),
                (item_specs["missing"][0], Decimal("-20.000000")),
                (item_specs["zero"][0], Decimal("9.000000")),
                (item_specs["archived"][0], Decimal("99.000000")),
            ):
                assert await connection.scalar(
                    text(
                        "SELECT quantity FROM stock_balances "
                        "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                    ),
                    {"warehouse_id": warehouse_id, "item_id": item_id},
                ) == expected

        concurrent_orders = await asyncio.gather(
            new_order(((component(coffee_id, "Coffee", UnitCode.G, "18"),),)),
            new_order(((component(coffee_id, "Coffee", UnitCode.G, "18"),),)),
        )
        await asyncio.gather(*(pay(order) for order in concurrent_orders))
        async with engine.connect() as connection:
            assert await connection.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": coffee_id},
            ) == Decimal("1874.000000")
            assert await connection.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions WHERE type='SALE' "
                    "AND reference_id = ANY(:order_ids)"
                ),
                {"order_ids": [order.id for order in concurrent_orders]},
            ) == 2

        async with sessions() as session:
            validator = SalesOrderReferenceValidator(
                SqlAlchemySalesRepository(session)
            )
            with pytest.raises(InvalidInventoryOperation):
                await validator.validate(
                    uuid4(), "ORDER", snapshot_order.id
                )
            with pytest.raises(InvalidInventoryOperation):
                await validator.validate(
                    context.organization_id, "GOODS_RECEIPT", snapshot_order.id
                )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_purchasing_atomic_posting_and_concurrency(
    postgres_inventory_database,
) -> None:
    database_url = postgres_inventory_database
    context, warehouse_id, item_id = await seed_inventory_context(database_url)
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def service_for(session, *, sink=None) -> PurchasingService:
        repository = SqlAlchemyPurchasingRepository(session)
        organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
        inventory = InventoryService(
            SqlAlchemyInventoryRepository(session),
            organizations,
            reference_validator=PurchasingReferenceValidator(repository),
        )
        return PurchasingService(
            repository,
            organizations,
            InventoryApplicationGateway(inventory),
            sink or OutboxEventSink(OutboxRepository(session)),
        )

    try:
        async with sessions() as session:
            location_id = await session.scalar(
                text("SELECT location_id FROM warehouses WHERE id=:warehouse_id"),
                {"warehouse_id": warehouse_id},
            )
            service = await service_for(session)
            supplier = await service.create_supplier(context, SupplierInput("PG Supplier"))
            order = await service.create_order(
                context,
                CreatePurchaseOrderCommand(
                    supplier.id,
                    location_id,
                    warehouse_id,
                    None,
                    "Concurrent receipt",
                    (PurchaseLineInput(item_id, Decimal("2"), "kg", None, Decimal("8000")),),
                ),
            )
            order = await service.submit_order(context, order.order.id)
            receipt = await service.create_receipt(
                context,
                CreateGoodsReceiptCommand(
                    supplier.id,
                    location_id,
                    warehouse_id,
                    order.order.id,
                    "INV-PG-1",
                    datetime.now(UTC),
                    None,
                    (
                        ReceiptLineInput(
                            item_id,
                            Decimal("1"),
                            "kg",
                            None,
                            Decimal("8000"),
                            order.lines[0].id,
                        ),
                    ),
                ),
            )

        async def post_once():
            async with sessions() as session:
                return await (await service_for(session)).post_receipt(
                    context, receipt.receipt.id, False
                )

        posted = await asyncio.gather(*(post_once() for _ in range(10)))
        assert {row.receipt.status for row in posted} == {GoodsReceiptStatus.POSTED}
        assert len({row.receipt.inventory_transaction_id for row in posted}) == 1

        async with sessions() as session:
            assert await session.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("1000")
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM inventory_transactions "
                        "WHERE organization_id=:organization_id "
                        "AND reference_type='GOODS_RECEIPT' AND reference_id=:receipt_id"
                    ),
                    {"organization_id": context.organization_id, "receipt_id": receipt.receipt.id},
                )
                == 1
            )
            posted_transaction_id = posted[0].receipt.inventory_transaction_id
            assert posted_transaction_id is not None
            assert (
                await session.execute(
                    text(
                        "SELECT event_name, event_version FROM outbox_events "
                        "WHERE aggregate_id=:transaction_id ORDER BY event_name"
                    ),
                    {"transaction_id": posted_transaction_id},
                )
            ).all() == [
                ("inventory.transaction_posted", 1),
                ("inventory.valuation_changed", 1),
            ]
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE event_name='inventory.cost_updated' "
                    "AND payload->>'inventory_item_id'=:item_id"
                ),
                {"item_id": str(item_id)},
            ) == 1
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE event_name='purchasing.goods_receipt_posted' "
                    "AND aggregate_id=:receipt_id"
                ),
                {"receipt_id": receipt.receipt.id},
            ) == 1
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM outbox_events "
                    "WHERE event_name='purchasing.order_partially_received' "
                    "AND aggregate_id=:order_id"
                ),
                {"order_id": order.order.id},
            ) == 1

        async with sessions() as session:
            service = await service_for(session)
            second_receipt = await service.create_receipt(
                context,
                CreateGoodsReceiptCommand(
                    supplier.id,
                    location_id,
                    warehouse_id,
                    None,
                    "INV-PG-2",
                    datetime.now(UTC),
                    None,
                    (
                        ReceiptLineInput(
                            item_id,
                            Decimal("1"),
                            "kg",
                            None,
                            Decimal("9000"),
                            None,
                        ),
                    ),
                ),
            )
            third_receipt = await service.create_receipt(
                context,
                CreateGoodsReceiptCommand(
                    supplier.id,
                    location_id,
                    warehouse_id,
                    None,
                    "INV-PG-3",
                    datetime.now(UTC),
                    None,
                    (
                        ReceiptLineInput(
                            item_id,
                            Decimal("1"),
                            "kg",
                            None,
                            Decimal("10000"),
                            None,
                        ),
                    ),
                ),
            )

        async def post_distinct(receipt_id: UUID):
            async with sessions() as session:
                return await (await service_for(session)).post_receipt(context, receipt_id, False)

        await asyncio.gather(
            post_distinct(second_receipt.receipt.id),
            post_distinct(third_receipt.receipt.id),
        )
        async with sessions() as session:
            quantity, average = (
                await session.execute(
                    text(
                        "SELECT quantity, average_unit_cost FROM stock_balances "
                        "WHERE warehouse_id=:warehouse_id "
                        "AND inventory_item_id=:item_id"
                    ),
                    {"warehouse_id": warehouse_id, "item_id": item_id},
                )
            ).one()
            assert quantity == Decimal("3000")
            assert average == Decimal("9.000000")

        async def reverse_once():
            async with sessions() as session:
                return await (await service_for(session)).reverse_receipt(
                    context, receipt.receipt.id
                )

        reversals = await asyncio.gather(reverse_once(), reverse_once(), return_exceptions=True)
        assert sum(not isinstance(value, Exception) for value in reversals) == 1
        assert sum(isinstance(value, InvalidPurchasingOperation) for value in reversals) == 1
        async with sessions() as session:
            assert await session.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("2000")
            assert await session.scalar(
                text(
                    "SELECT average_unit_cost FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("9.500000")
            assert (
                await session.scalar(
                    text("SELECT status FROM purchase_orders WHERE id=:order_id"),
                    {"order_id": order.order.id},
                )
                == PurchaseOrderStatus.ORDERED.value
            )

        async with sessions() as session:
            failing_receipt = await (await service_for(session)).create_receipt(
                context,
                CreateGoodsReceiptCommand(
                    supplier.id,
                    location_id,
                    warehouse_id,
                    None,
                    "INV-PG-OUTBOX-FAIL",
                    datetime.now(UTC),
                    None,
                    (
                        ReceiptLineInput(
                            item_id,
                            Decimal("1"),
                            "kg",
                            None,
                            Decimal("11000"),
                            None,
                        ),
                    ),
                ),
            )
        async with sessions() as session:
            with pytest.raises(RuntimeError, match="forced outbox failure"):
                await (
                    await service_for(
                        session,
                        sink=OutboxEventSink(FailingOutboxRepository(session)),
                    )
                ).post_receipt(context, failing_receipt.receipt.id, False)
        async with sessions() as session:
            assert await session.scalar(
                text("SELECT status FROM goods_receipts WHERE id=:receipt_id"),
                {"receipt_id": failing_receipt.receipt.id},
            ) == GoodsReceiptStatus.DRAFT.value
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM inventory_transactions "
                    "WHERE reference_type='GOODS_RECEIPT' AND reference_id=:receipt_id"
                ),
                {"receipt_id": failing_receipt.receipt.id},
            ) == 0
            assert await session.scalar(
                text(
                    "SELECT quantity FROM stock_balances "
                    "WHERE warehouse_id=:warehouse_id AND inventory_item_id=:item_id"
                ),
                {"warehouse_id": warehouse_id, "item_id": item_id},
            ) == Decimal("2000")
            assert (
                await session.execute(
                    select(OutboxEventModel.event_name).where(
                        OutboxEventModel.aggregate_id == failing_receipt.receipt.id
                    )
                )
            ).scalars().all() == ["purchasing.goods_receipt_created"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_postgres_migration_from_zero_and_rollback() -> None:
    source_url = os.getenv("POSTGRES_TEST_URL")
    if not source_url:
        pytest.skip("POSTGRES_TEST_URL is required for the PostgreSQL integration gate")

    database_name = f"beanly_stage2_{uuid4().hex}"
    source = make_url(source_url)
    admin_url = source.set(database="postgres").render_as_string(hide_password=False)
    test_url = source.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        config = alembic_config(test_url)
        await asyncio.to_thread(command.upgrade, config, "0002_organizations")
        (
            legacy_user_id,
            legacy_organization_id,
            legacy_location_id,
            legacy_membership_id,
        ) = await seed_stage_two_owner(test_url)
        await asyncio.to_thread(command.upgrade, config, "0006_purchasing")
        legacy_warehouse_id, legacy_line_id = await seed_legacy_inventory_ledger(
            test_url,
            legacy_user_id,
            legacy_organization_id,
            legacy_location_id,
        )
        await asyncio.to_thread(command.upgrade, config, "head")
        upgraded = await database_snapshot(test_url)

        assert {
            "users",
            "auth_sessions",
            "alembic_version",
            *APPLICATION_TABLES,
        } <= upgraded["tables"]
        assert upgraded["revision"] == "0021_refunds_fiscal_tax"
        assert INVENTORY_OPERATION_TABLES <= upgraded["tables"]
        assert {
            "inventory_writeoff_number_seq",
            "inventory_count_number_seq",
            "inventory_transfer_number_seq",
            "supplier_return_number_seq",
        } <= upgraded["sequences"]
        assert {
            "organization_id",
            "location_id",
            "warehouse_id",
            "number",
            "reason_id",
            "status",
            "occurred_at",
            "inventory_transaction_id",
            "total_cost_amount",
        } <= set(upgraded["columns"]["inventory_writeoffs"])
        assert str(upgraded["columns"]["inventory_count_lines"]["counted_quantity"]["type"]) == (
            "NUMERIC(20, 6)"
        )
        assert {
            "ck_inventory_transfer_status",
            "ck_inventory_transfer_distinct_warehouses",
        } <= upgraded["check_constraints"]["inventory_transfers"]
        assert {
            "ck_inventory_count_type",
            "ck_inventory_count_status",
        } <= upgraded["check_constraints"]["inventory_counts"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["inventory_writeoffs"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["inventory_counts"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["inventory_transfers"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["supplier_returns"]
        assert {
            "ix_inventory_writeoffs_organization_status_occurred",
        } <= upgraded["indexes"]["inventory_writeoffs"]
        assert {
            "ix_inventory_counts_organization_status_snapshot",
        } <= upgraded["indexes"]["inventory_counts"]
        assert {
            "ix_inventory_transfers_organization_status_occurred",
        } <= upgraded["indexes"]["inventory_transfers"]
        assert {
            "ix_supplier_returns_organization_status_returned",
        } <= upgraded["indexes"]["supplier_returns"]

        await asyncio.to_thread(
            command.downgrade, config, "0013_transactional_outbox"
        )
        inventory_operations_downgraded = await database_snapshot(test_url)
        assert not (
            INVENTORY_OPERATION_TABLES | FINANCE_TABLES
        ) & inventory_operations_downgraded["tables"]
        assert inventory_operations_downgraded["revision"] == "0013_transactional_outbox"
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.check, config)
        assert await membership_state(test_url, legacy_membership_id) == ("ACTIVE", "ALL")
        assert set(upgraded["columns"]["organizations"]) == {
            "id",
            "name",
            "country_code",
            "currency_code",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["locations"]) == {
            "id",
            "organization_id",
            "name",
            "timezone",
            "address",
            "is_active",
            "is_primary",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["organization_memberships"]) == {
            "id",
            "organization_id",
            "user_id",
            "role",
            "status",
            "location_access",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["employees"]) == {
            "id",
            "organization_id",
            "user_id",
            "first_name",
            "last_name",
            "phone",
            "position",
            "status",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["organization_invitations"]) == {
            "id",
            "organization_id",
            "employee_id",
            "email",
            "role",
            "token_hash",
            "status",
            "expires_at",
            "invited_by",
            "accepted_by",
            "accepted_at",
            "created_at",
        }
        assert set(upgraded["columns"]["warehouses"]) == {
            "id",
            "organization_id",
            "location_id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["inventory_items"]) == {
            "id",
            "organization_id",
            "name",
            "sku",
            "base_unit",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["stock_balances"]) == {
            "id",
            "organization_id",
            "location_id",
            "warehouse_id",
            "inventory_item_id",
            "quantity",
            "average_unit_cost",
            "updated_at",
        }
        assert set(upgraded["columns"]["inventory_transactions"]) == {
            "id",
            "organization_id",
            "location_id",
            "warehouse_id",
            "type",
            "status",
            "reference_type",
            "reference_id",
            "idempotency_key",
            "note",
            "created_by",
            "created_at",
            "posted_at",
            "reversal_of_id",
        }
        assert set(upgraded["columns"]["inventory_transaction_lines"]) == {
            "id",
            "transaction_id",
            "inventory_item_id",
            "quantity_delta",
            "requested_unit_cost_amount",
            "requested_total_cost_amount",
            "unit_cost_amount",
            "total_cost_amount",
            "quantity_after",
            "average_unit_cost_after",
            "created_at",
        }
        for table, column in {
            "warehouses": "created_at",
            "inventory_items": "updated_at",
            "stock_balances": "updated_at",
            "inventory_transactions": "created_at",
            "inventory_transaction_lines": "created_at",
        }.items():
            assert upgraded["columns"][table][column]["nullable"] is False
            assert upgraded["columns"][table][column]["type"].timezone
        assert str(upgraded["columns"]["stock_balances"]["quantity"]["type"]) == ("NUMERIC(20, 6)")
        assert (
            str(upgraded["columns"]["stock_balances"]["average_unit_cost"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert (
            str(upgraded["columns"]["inventory_transaction_lines"]["quantity_delta"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert (
            str(upgraded["columns"]["inventory_transaction_lines"]["unit_cost_amount"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert upgraded["columns"]["organizations"]["created_at"]["type"].timezone
        assert upgraded["columns"]["locations"]["updated_at"]["type"].timezone
        assert upgraded["indexes"]["organizations"] == {"ix_organizations_created_by"}
        assert upgraded["indexes"]["locations"] == {"ix_locations_organization_id"}
        assert {
            "ix_organization_memberships_organization_id",
            "ix_organization_memberships_user_id",
        } <= upgraded["indexes"]["organization_memberships"]
        assert (("created_by",), "users") in upgraded["foreign_keys"]["organizations"]
        assert (
            ("organization_id",),
            "organizations",
        ) in upgraded["foreign_keys"]["locations"]
        membership_keys = upgraded["foreign_keys"]["organization_memberships"]
        assert (("organization_id",), "organizations") in membership_keys
        assert (("user_id",), "users") in membership_keys
        assert (
            "organization_id",
            "user_id",
        ) in upgraded["unique_constraints"]["organization_memberships"]
        assert {
            "ix_organization_invitations_organization_id",
            "ix_organization_invitations_email",
            "ix_organization_invitations_token_hash",
            "uq_pending_invitation_organization_email",
        } <= upgraded["indexes"]["organization_invitations"]
        assert {
            "ix_employees_organization_id",
            "ix_employees_user_id",
        } <= upgraded["indexes"]["employees"]
        assert {
            "ix_membership_locations_membership_id",
            "ix_membership_locations_location_id",
        } <= upgraded["indexes"]["membership_locations"]
        assert upgraded["primary_keys"]["membership_locations"] == (
            "membership_id",
            "location_id",
        )
        assert (
            ("organization_id",),
            "organizations",
        ) in upgraded["foreign_keys"]["employees"]
        assert (
            ("employee_id",),
            "employees",
        ) in upgraded["foreign_keys"]["employee_locations"]

        assert {
            "ix_inventory_transactions_organization_id",
            "ix_inventory_transactions_warehouse_id",
            "ix_inventory_transactions_created_at",
            "ix_inventory_transactions_reference_type",
            "ix_inventory_transactions_reference_id",
            "uq_inventory_transactions_idempotency",
        } <= upgraded["indexes"]["inventory_transactions"]
        assert {
            "ix_inventory_transaction_lines_transaction_id",
            "ix_inventory_transaction_lines_inventory_item_id",
        } <= upgraded["indexes"]["inventory_transaction_lines"]
        assert (
            "warehouse_id",
            "inventory_item_id",
        ) in upgraded["unique_constraints"]["stock_balances"]
        assert ("reversal_of_id",) in upgraded["unique_constraints"]["inventory_transactions"]
        transaction_keys = upgraded["foreign_keys"]["inventory_transactions"]
        assert (("warehouse_id",), "warehouses") in transaction_keys
        assert (("created_by",), "users") in transaction_keys
        assert (("reversal_of_id",), "inventory_transactions") in transaction_keys
        line_keys = upgraded["foreign_keys"]["inventory_transaction_lines"]
        assert (("transaction_id",), "inventory_transactions") in line_keys
        assert (("inventory_item_id",), "inventory_items") in line_keys
        balance_keys = upgraded["foreign_keys"]["stock_balances"]
        assert (("warehouse_id",), "warehouses") in balance_keys
        assert (("inventory_item_id",), "inventory_items") in balance_keys

        assert {
            "ix_suppliers_organization_id",
            "ix_suppliers_organization_name",
        } <= upgraded["indexes"]["suppliers"]
        assert {
            "ix_purchase_orders_organization_id",
            "ix_purchase_orders_supplier_id",
            "ix_purchase_orders_organization_status_created",
        } <= upgraded["indexes"]["purchase_orders"]
        assert {
            "ix_goods_receipts_organization_id",
            "ix_goods_receipts_purchase_order_id",
            "ix_goods_receipts_organization_status_received",
        } <= upgraded["indexes"]["goods_receipts"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["purchase_orders"]
        assert (
            "organization_id",
            "number",
        ) in upgraded["unique_constraints"]["goods_receipts"]
        assert ("inventory_transaction_id",) in upgraded["unique_constraints"]["goods_receipts"]
        receipt_keys = upgraded["foreign_keys"]["goods_receipts"]
        assert (("organization_id",), "organizations") in receipt_keys
        assert (("warehouse_id",), "warehouses") in receipt_keys
        assert (("purchase_order_id",), "purchase_orders") in receipt_keys
        assert (("inventory_transaction_id",), "inventory_transactions") in receipt_keys
        assert (
            str(upgraded["columns"]["goods_receipt_lines"]["base_quantity"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert upgraded["columns"]["goods_receipts"]["received_at"]["type"].timezone
        assert set(upgraded["columns"]["product_variants"]) >= {
            "organization_id",
            "product_id",
            "base_price_minor",
            "is_default",
            "status",
        }
        assert str(upgraded["columns"]["recipe_components"]["quantity"]["type"]) == (
            "NUMERIC(20, 6)"
        )
        assert ("product_variant_id",) in upgraded["unique_constraints"]["recipes"]
        assert (
            "recipe_id",
            "inventory_item_id",
        ) in upgraded["unique_constraints"]["recipe_components"]
        assert {
            "uq_product_variants_organization_sku",
            "uq_product_variants_active_default",
            "ix_product_variants_product_id",
        } <= upgraded["indexes"]["product_variants"]
        assert (
            "location_id",
            "product_variant_id",
        ) in upgraded["unique_constraints"]["variant_prices"]
        assert (
            "location_id",
            "product_id",
        ) in upgraded["unique_constraints"]["product_location_settings"]
        assert (
            ("inventory_item_id",),
            "inventory_items",
        ) in upgraded["foreign_keys"]["recipe_components"]
        assert (
            ("location_id",),
            "locations",
        ) in upgraded["foreign_keys"]["variant_prices"]
        assert upgraded["columns"]["recipes"]["updated_at"]["type"].timezone
        assert str(upgraded["columns"]["modifier_option_components"]["quantity_delta"]["type"]) == (
            "NUMERIC(20, 6)"
        )
        assert str(upgraded["columns"]["modifier_options"]["base_price_delta_minor"]["type"]) == (
            "BIGINT"
        )
        assert (
            "modifier_option_id",
            "inventory_item_id",
        ) in upgraded["unique_constraints"]["modifier_option_components"]
        assert (
            "location_id",
            "modifier_option_id",
        ) in upgraded["unique_constraints"]["modifier_option_prices"]
        assert (
            "location_id",
            "modifier_option_id",
        ) in upgraded["unique_constraints"]["modifier_option_location_settings"]
        assert (
            ("product_variant_id",),
            "product_variants",
        ) in upgraded["foreign_keys"]["modifier_groups"]
        assert (
            ("inventory_item_id",),
            "inventory_items",
        ) in upgraded["foreign_keys"]["modifier_option_components"]
        assert {
            "ck_modifier_group_selection_type",
            "ck_modifier_group_min_nonnegative",
            "ck_modifier_group_max_positive",
            "ck_modifier_group_min_max",
            "ck_modifier_group_single_max",
        } <= upgraded["check_constraints"]["modifier_groups"]
        assert {"ck_modifier_option_price_nonnegative"} <= upgraded["check_constraints"][
            "modifier_options"
        ]
        assert {"ck_modifier_component_quantity_nonzero"} <= upgraded[
            "check_constraints"
        ]["modifier_option_components"]
        assert {"ck_modifier_price_nonnegative"} <= upgraded["check_constraints"][
            "modifier_option_prices"
        ]
        assert "sales_order_number_seq" in upgraded["sequences"]
        assert (
            "organization_id",
            "location_id",
            "name",
        ) in upgraded["unique_constraints"]["pos_registers"]
        assert (
            "organization_id",
            "client_order_id",
        ) in upgraded["unique_constraints"]["sales_orders"]
        assert (
            "order_id",
            "client_item_id",
        ) in upgraded["unique_constraints"]["sales_order_items"]
        assert str(upgraded["columns"]["sales_orders"]["number"]["type"]) == "BIGINT"
        assert (
            str(upgraded["columns"]["sales_order_item_components"]["quantity_per_unit"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert {
            "ck_sales_order_type",
            "ck_sales_order_status",
            "ck_order_guest_count",
            "ck_order_subtotal_nonnegative",
            "ck_order_total_nonnegative",
        } <= upgraded["check_constraints"]["sales_orders"]
        assert {"ck_register_shift_status"} <= upgraded["check_constraints"][
            "register_shifts"
        ]
        assert {
            "ck_sales_order_item_quantity",
            "ck_order_item_base_price",
            "ck_order_item_modifier_price",
            "ck_order_item_unit_price",
            "ck_order_item_line_total",
        } <= upgraded["check_constraints"]["sales_order_items"]
        assert {"ck_order_item_component_quantity"} <= upgraded["check_constraints"][
            "sales_order_item_components"
        ]
        assert {
            "ix_pos_registers_organization_id",
            "ix_pos_registers_location_id",
        } <= upgraded["indexes"]["pos_registers"]
        assert {
            "ix_register_shifts_organization_id",
            "ix_register_shifts_location_id",
            "ix_register_shifts_register_id",
            "ix_register_shifts_status",
            "uq_register_shifts_open_register",
        } <= upgraded["indexes"]["register_shifts"]
        assert {
            "ix_sales_orders_organization_id",
            "ix_sales_orders_location_id",
            "ix_sales_orders_shift_id",
            "ix_sales_orders_status",
            "ix_sales_orders_created_at",
        } <= upgraded["indexes"]["sales_orders"]
        assert {"paid_by_user_id", "paid_at"} <= set(
            upgraded["columns"]["sales_orders"]
        )
        assert upgraded["columns"]["sales_orders"]["paid_by_user_id"]["nullable"]
        assert upgraded["columns"]["sales_orders"]["paid_at"]["nullable"]
        assert upgraded["columns"]["sales_orders"]["paid_at"]["type"].timezone
        assert {
            "inventory_transaction_id",
            "cogs_amount",
            "cogs_status",
        } <= set(upgraded["columns"]["sales_orders"])
        assert upgraded["columns"]["sales_orders"]["inventory_transaction_id"][
            "nullable"
        ]
        assert upgraded["columns"]["sales_orders"]["cogs_amount"]["nullable"]
        assert upgraded["columns"]["sales_orders"]["cogs_status"]["nullable"]
        assert (
            str(upgraded["columns"]["sales_orders"]["cogs_amount"]["type"])
            == "NUMERIC(20, 6)"
        )
        assert (
            ("paid_by_user_id",),
            "users",
        ) in upgraded["foreign_keys"]["sales_orders"]
        assert (
            ("inventory_transaction_id",),
            "inventory_transactions",
        ) in upgraded["foreign_keys"]["sales_orders"]
        assert ("inventory_transaction_id",) in upgraded["unique_constraints"][
            "sales_orders"
        ]
        assert {
            "ck_sales_order_cogs_nonnegative",
            "ck_sales_order_cogs_status",
        } <= upgraded["check_constraints"]["sales_orders"]
        assert set(upgraded["columns"]["payments"]) == {
            "id",
            "organization_id",
            "location_id",
            "order_id",
            "shift_id",
            "client_payment_id",
            "currency_code",
            "amount_minor",
            "created_by_user_id",
            "offline_session_id",
            "completed_at",
            "created_at",
            "updated_at",
        }
        assert set(upgraded["columns"]["payment_lines"]) == {
            "id",
            "payment_id",
            "method",
            "amount_minor",
            "cash_received_minor",
            "change_minor",
            "reference",
            "sort_order",
            "created_at",
        }
        assert str(upgraded["columns"]["payments"]["amount_minor"]["type"]) == "BIGINT"
        assert str(upgraded["columns"]["payment_lines"]["amount_minor"]["type"]) == (
            "BIGINT"
        )
        assert upgraded["columns"]["payments"]["completed_at"]["type"].timezone
        assert upgraded["columns"]["payment_lines"]["created_at"]["type"].timezone
        assert {
            "ix_payments_organization_id",
            "ix_payments_location_id",
            "ix_payments_shift_id",
            "ix_payments_completed_at",
        } <= upgraded["indexes"]["payments"]
        assert {
            "ix_payment_lines_payment_id",
            "ix_payment_lines_method",
        } <= upgraded["indexes"]["payment_lines"]
        assert ("order_id",) in upgraded["unique_constraints"]["payments"]
        assert (
            "organization_id",
            "client_payment_id",
        ) in upgraded["unique_constraints"]["payments"]
        assert {
            "ck_payment_amount_nonnegative",
        } <= upgraded["check_constraints"]["payments"]
        assert {
            "ck_payment_line_method",
            "ck_payment_line_amount_nonnegative",
            "ck_payment_line_change_nonnegative",
            "ck_payment_line_sort_nonnegative",
            "ck_payment_line_cash_values",
        } <= upgraded["check_constraints"]["payment_lines"]
        assert (("order_id",), "sales_orders") in upgraded["foreign_keys"]["payments"]
        assert (("payment_id",), "payments") in upgraded["foreign_keys"][
            "payment_lines"
        ]
        assert set(upgraded["columns"]["outbox_events"]) == {
            "id",
            "organization_id",
            "event_name",
            "event_version",
            "aggregate_type",
            "aggregate_id",
            "payload",
            "occurred_at",
            "available_at",
            "attempts",
            "locked_by",
            "locked_until",
            "processed_at",
            "dead_lettered_at",
            "last_error",
            "created_at",
        }
        assert {
            "ix_outbox_pending",
            "ix_outbox_events_organization_id",
            "ix_outbox_event_name",
            "ix_outbox_aggregate",
        } <= upgraded["indexes"]["outbox_events"]
        assert {
            "ck_outbox_event_version_positive",
            "ck_outbox_attempts_nonnegative",
            "ck_outbox_lock_pair",
            "ck_outbox_terminal_state",
        } <= upgraded["check_constraints"]["outbox_events"]
        assert (("organization_id",), "organizations") in upgraded["foreign_keys"][
            "outbox_events"
        ]
        assert upgraded["primary_keys"]["outbox_events"] == ("id",)
        assert str(upgraded["columns"]["outbox_events"]["payload"]["type"]) == "JSONB"
        for column in ("occurred_at", "available_at", "created_at"):
            assert not upgraded["columns"]["outbox_events"][column]["nullable"]
            assert upgraded["columns"]["outbox_events"][column]["type"].timezone
        for column in (
            "locked_until",
            "processed_at",
            "dead_lettered_at",
        ):
            assert upgraded["columns"]["outbox_events"][column]["type"].timezone

        legacy_engine = create_async_engine(test_url)
        try:
            async with legacy_engine.connect() as connection:
                assert await connection.scalar(
                    text(
                        "SELECT average_unit_cost FROM stock_balances "
                        "WHERE warehouse_id=:warehouse_id"
                    ),
                    {"warehouse_id": legacy_warehouse_id},
                ) == Decimal("2.000000")
                legacy_snapshot = (
                    await connection.execute(
                        text(
                            "SELECT requested_unit_cost_amount, "
                            "requested_total_cost_amount, unit_cost_amount, "
                            "total_cost_amount, quantity_after, average_unit_cost_after "
                            "FROM inventory_transaction_lines WHERE id=:line_id"
                        ),
                        {"line_id": legacy_line_id},
                    )
                ).one()
                assert legacy_snapshot == (
                    Decimal("2.000000"),
                    None,
                    Decimal("2.000000"),
                    Decimal("20.000000"),
                    Decimal("10.000000"),
                    Decimal("2.000000"),
                )
        finally:
            await legacy_engine.dispose()

        await asyncio.to_thread(command.downgrade, config, "0012_sale_posting")
        outbox_downgraded = await database_snapshot(test_url)
        assert not OUTBOX_TABLES & outbox_downgraded["tables"]
        assert outbox_downgraded["revision"] == "0012_sale_posting"
        await asyncio.to_thread(command.upgrade, config, "0013_transactional_outbox")
        outbox_reupgraded = await database_snapshot(test_url)
        assert OUTBOX_TABLES <= outbox_reupgraded["tables"]
        assert outbox_reupgraded["revision"] == "0013_transactional_outbox"

        await asyncio.to_thread(command.downgrade, config, "0011_payments")
        sale_posting_downgraded = await database_snapshot(test_url)
        assert PAYMENT_TABLES <= sale_posting_downgraded["tables"]
        assert not OUTBOX_TABLES & sale_posting_downgraded["tables"]
        assert {
            "inventory_transaction_id",
            "cogs_amount",
            "cogs_status",
        }.isdisjoint(sale_posting_downgraded["columns"]["sales_orders"])
        assert sale_posting_downgraded["revision"] == "0011_payments"
        await asyncio.to_thread(command.upgrade, config, "0012_sale_posting")
        sale_posting_reupgraded = await database_snapshot(test_url)
        assert sale_posting_reupgraded["revision"] == "0012_sale_posting"
        assert {
            "inventory_transaction_id",
            "cogs_amount",
            "cogs_status",
        } <= set(sale_posting_reupgraded["columns"]["sales_orders"])

        await asyncio.to_thread(command.downgrade, config, "0010_sales_pos")
        payments_downgraded = await database_snapshot(test_url)
        assert not PAYMENT_TABLES & payments_downgraded["tables"]
        assert SALES_TABLES <= payments_downgraded["tables"]
        assert {"paid_by_user_id", "paid_at"}.isdisjoint(
            payments_downgraded["columns"]["sales_orders"]
        )
        assert payments_downgraded["revision"] == "0010_sales_pos"
        await asyncio.to_thread(command.upgrade, config, "head")

        await asyncio.to_thread(command.downgrade, config, "0009_modifiers")
        sales_downgraded = await database_snapshot(test_url)
        assert not (SALES_TABLES | PAYMENT_TABLES) & sales_downgraded["tables"]
        assert APPLICATION_TABLES - (
            SALES_TABLES
            | PAYMENT_TABLES
            | OUTBOX_TABLES
            | INVENTORY_OPERATION_TABLES
            | FINANCE_TABLES
            | OFFLINE_POS_TABLES
        ) <= sales_downgraded["tables"]
        assert "sales_order_number_seq" not in sales_downgraded["sequences"]
        assert sales_downgraded["revision"] == "0009_modifiers"
        await asyncio.to_thread(command.upgrade, config, "head")

        await asyncio.to_thread(command.downgrade, config, "0008_menu")
        modifiers_downgraded = await database_snapshot(test_url)
        assert not MENU_MODIFIER_TABLES & modifiers_downgraded["tables"]
        assert (MENU_TABLES - MENU_MODIFIER_TABLES) <= modifiers_downgraded["tables"]
        assert modifiers_downgraded["revision"] == "0008_menu"
        await asyncio.to_thread(command.upgrade, config, "head")

        await asyncio.to_thread(command.downgrade, config, "0007_inventory_valuation")
        menu_downgraded = await database_snapshot(test_url)
        assert not MENU_TABLES & menu_downgraded["tables"]
        assert INVENTORY_LEDGER_TABLES <= menu_downgraded["tables"]
        assert menu_downgraded["revision"] == "0007_inventory_valuation"
        await asyncio.to_thread(command.upgrade, config, "head")

        await asyncio.to_thread(command.downgrade, config, "0005_inventory_ledger")
        purchasing_downgraded = await database_snapshot(test_url)
        assert not PURCHASING_TABLES & purchasing_downgraded["tables"]
        assert INVENTORY_LEDGER_TABLES <= purchasing_downgraded["tables"]
        assert purchasing_downgraded["revision"] == "0005_inventory_ledger"
        await asyncio.to_thread(command.upgrade, config, "head")

        index_engine = create_async_engine(test_url)
        try:
            async with index_engine.connect() as connection:
                index_definition = await connection.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname='uq_inventory_transactions_idempotency'"
                    )
                )
                open_shift_index = await connection.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname='uq_register_shifts_open_register'"
                    )
                )
                outbox_pending_index = await connection.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname='ix_outbox_pending'"
                    )
                )
        finally:
            await index_engine.dispose()
        assert index_definition is not None
        assert "UNIQUE" in index_definition
        assert "WHERE (idempotency_key IS NOT NULL)" in index_definition
        assert open_shift_index is not None
        assert "UNIQUE" in open_shift_index
        assert "WHERE" in open_shift_index
        assert "status" in open_shift_index
        assert "OPEN" in open_shift_index
        assert outbox_pending_index is not None
        assert "available_at, occurred_at" in outbox_pending_index
        assert "processed_at IS NULL" in outbox_pending_index
        assert "dead_lettered_at IS NULL" in outbox_pending_index

        inventory_context, inventory_warehouse_id, inventory_item_id = await seed_inventory_context(
            test_url
        )
        ledger_engine = create_async_engine(test_url)
        ledger_sessions = async_sessionmaker(ledger_engine, expire_on_commit=False)
        try:
            async with ledger_sessions() as session:
                await InventoryService(
                    SqlAlchemyInventoryRepository(session),
                    OrganizationService(SqlAlchemyOrganizationRepository(session)),
                ).create_and_post(
                    inventory_context,
                    CreateAndPostCommand(
                        inventory_context.organization_id,
                        inventory_context.user_id,
                        inventory_warehouse_id,
                        InventoryTransactionType.ADJUSTMENT,
                        "Migration projection",
                        (
                            QuantityInput(
                                inventory_item_id,
                                Decimal("12.5"),
                                UnitCode.G,
                                Decimal("1"),
                            ),
                        ),
                        "migration:projection",
                    ),
                )
            async with ledger_engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM stock_balances "
                            "WHERE warehouse_id=:warehouse_id AND quantity <> 0"
                        ),
                        {"warehouse_id": inventory_warehouse_id},
                    )
                    == 1
                )
        finally:
            await ledger_engine.dispose()

        await asyncio.to_thread(command.downgrade, config, "0004_inventory_core")
        ledger_downgraded = await database_snapshot(test_url)
        assert not INVENTORY_LEDGER_TABLES & ledger_downgraded["tables"]
        assert INVENTORY_CORE_TABLES <= ledger_downgraded["tables"]
        assert ledger_downgraded["revision"] == "0004_inventory_core"
        projection_engine = create_async_engine(test_url)
        try:
            async with projection_engine.connect() as connection:
                assert await connection.scalar(text("SELECT count(*) FROM stock_balances")) == 0
        finally:
            await projection_engine.dispose()
        await asyncio.to_thread(command.upgrade, config, "head")
        reledger_engine = create_async_engine(test_url)
        try:
            async with reledger_engine.connect() as connection:
                balance_total = await connection.scalar(
                    text("SELECT COALESCE(SUM(quantity), 0) FROM stock_balances")
                )
                ledger_total = await connection.scalar(
                    text(
                        "SELECT COALESCE(SUM(line.quantity_delta), 0) "
                        "FROM inventory_transaction_lines line "
                        "JOIN inventory_transactions tx ON tx.id=line.transaction_id "
                        "WHERE tx.status IN ('POSTED', 'REVERSED')"
                    )
                )
                assert balance_total == ledger_total == Decimal(0)
        finally:
            await reledger_engine.dispose()

        await assert_real_transaction_rollback(test_url)
        await assert_postgres_invitation_parent_is_flushed_first(test_url)

        await asyncio.to_thread(command.downgrade, config, "0002_organizations")
        downgraded = await database_snapshot(test_url)
        assert not TEAM_TABLES & downgraded["tables"]
        assert not (INVENTORY_CORE_TABLES | INVENTORY_LEDGER_TABLES) & downgraded["tables"]
        assert ORGANIZATION_TABLES <= downgraded["tables"]
        assert downgraded["revision"] == "0002_organizations"

        downgraded_engine = create_async_engine(test_url)
        try:
            async with downgraded_engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT status FROM organization_memberships WHERE id = :membership_id"
                        ),
                        {"membership_id": legacy_membership_id},
                    )
                    == "active"
                )
        finally:
            await downgraded_engine.dispose()

        await asyncio.to_thread(command.upgrade, config, "head")
        reupgraded = await database_snapshot(test_url)
        assert APPLICATION_TABLES <= reupgraded["tables"]
        assert reupgraded["revision"] == "0021_refunds_fiscal_tax"
        assert await membership_state(test_url, legacy_membership_id) == ("ACTIVE", "ALL")
    finally:
        await admin_engine.dispose()
        cleanup_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with cleanup_engine.connect() as connection:
                statement = text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                await connection.execute(statement)
        finally:
            await cleanup_engine.dispose()
