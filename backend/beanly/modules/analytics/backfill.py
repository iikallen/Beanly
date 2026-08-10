import argparse
import asyncio
from datetime import date
from uuid import UUID

from beanly.core.database.session import engine, session_factory
from beanly.modules.analytics.application.backfill_service import (
    AnalyticsBackfillService,
)
from beanly.modules.analytics.application.projection_service import (
    AnalyticsProjectionService,
)
from beanly.modules.analytics.infrastructure.db.repositories import (
    SqlAlchemyAnalyticsRepository,
)
from beanly.modules.analytics.infrastructure.source_reader import (
    SqlAlchemyAnalyticsSourceReader,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild incremental analytics rows")
    parser.add_argument("--organization-id", type=UUID)
    parser.add_argument("--date-from", type=date.fromisoformat)
    parser.add_argument("--date-to", type=date.fromisoformat)
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


async def _main() -> None:
    args = _arguments()
    try:
        async with session_factory() as session:
            repository = SqlAlchemyAnalyticsRepository(session)
            sources = SqlAlchemyAnalyticsSourceReader(session)
            result = await AnalyticsBackfillService(
                AnalyticsProjectionService(repository, sources), sources, repository
            ).run(
                organization_id=args.organization_id,
                date_from=args.date_from,
                date_to=args.date_to,
                batch_size=args.batch_size,
            )
            print(
                "Analytics backfill complete: "
                f"payments={result.payments} "
                f"inventory_transactions={result.inventory_transactions} "
                f"expenses_posted={result.expenses_posted} "
                f"expenses_reversed={result.expenses_reversed}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
