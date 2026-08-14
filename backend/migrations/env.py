from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from beanly.core.config.settings import get_settings
from beanly.core.database.base import Base
from beanly.core.events.outbox import models as outbox_models  # noqa: F401
from beanly.core.security import audit as security_audit_models  # noqa: F401
from beanly.modules.analytics.infrastructure.db import models as analytics_models  # noqa: F401
from beanly.modules.cash_management.infrastructure.db import (
    models as cash_management_models,  # noqa: F401
)
from beanly.modules.customers.infrastructure.db import models as customer_models  # noqa: F401
from beanly.modules.employees.infrastructure.db import models as employee_models  # noqa: F401
from beanly.modules.finance.infrastructure.db import models as finance_models  # noqa: F401
from beanly.modules.fiscal.infrastructure.db import models as fiscal_models  # noqa: F401
from beanly.modules.identity.infrastructure.db import models  # noqa: F401
from beanly.modules.integrations.infrastructure.db import (
    models as integration_models,  # noqa: F401
)
from beanly.modules.inventory.infrastructure.db import models as inventory_models  # noqa: F401
from beanly.modules.kitchen.infrastructure.db import models as kitchen_models  # noqa: F401
from beanly.modules.menu.infrastructure.db import models as menu_models  # noqa: F401
from beanly.modules.offline_pos.infrastructure.db import models as offline_pos_models  # noqa: F401
from beanly.modules.onboarding.infrastructure.db import models as onboarding_models  # noqa: F401
from beanly.modules.organizations.infrastructure.db import (
    models as organization_models,  # noqa: F401
)
from beanly.modules.payments.infrastructure.db import models as payment_models  # noqa: F401
from beanly.modules.promotions.infrastructure.db import models as promotion_models  # noqa: F401
from beanly.modules.purchasing.infrastructure.db import (
    models as purchasing_models,  # noqa: F401
)
from beanly.modules.refunds.infrastructure.db import models as refund_models  # noqa: F401
from beanly.modules.sales.infrastructure.db import models as sales_models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
