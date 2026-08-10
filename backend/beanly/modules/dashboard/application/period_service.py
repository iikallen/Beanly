from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from beanly.modules.dashboard.application.dto import DateTimeRange, ResolvedPeriod
from beanly.modules.dashboard.domain.enums import DashboardPeriod, TrendBucket


class InvalidDashboardPeriod(ValueError):
    pass


class PeriodService:
    def resolve(
        self,
        period: DashboardPeriod,
        timezone: str,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        now: datetime | None = None,
    ) -> ResolvedPeriod:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise InvalidDashboardPeriod("Unknown reporting timezone") from exc
        instant = now or datetime.now(UTC)
        if instant.utcoffset() is None:
            raise InvalidDashboardPeriod("now must include a timezone")
        local_now = instant.astimezone(zone)

        if period is DashboardPeriod.CUSTOM:
            if date_from is None or date_to is None:
                raise InvalidDashboardPeriod("date_from and date_to are required for CUSTOM")
            if date_from > date_to:
                raise InvalidDashboardPeriod("date_from must not be after date_to")
            if (date_to - date_from).days + 1 > 90:
                raise InvalidDashboardPeriod("CUSTOM period cannot exceed 90 days")
            current_start = _midnight(date_from, zone)
            current_end = _midnight(date_to + timedelta(days=1), zone)
        elif date_from is not None or date_to is not None:
            raise InvalidDashboardPeriod("date_from and date_to are only valid for CUSTOM")
        elif period is DashboardPeriod.TODAY:
            current_start = _midnight(local_now.date(), zone)
            current_end = local_now
        elif period is DashboardPeriod.YESTERDAY:
            current_end = _midnight(local_now.date(), zone)
            current_start = _midnight(local_now.date() - timedelta(days=1), zone)
        elif period is DashboardPeriod.LAST_7_DAYS:
            current_start = _midnight(local_now.date() - timedelta(days=6), zone)
            current_end = local_now
        else:
            current_start = _midnight(local_now.date().replace(day=1), zone)
            current_end = local_now

        if period is DashboardPeriod.TODAY:
            previous_start = _midnight(local_now.date() - timedelta(days=1), zone)
            previous_end = datetime.combine(
                local_now.date() - timedelta(days=1),
                local_now.timetz().replace(tzinfo=None),
                zone,
            )
        elif period is DashboardPeriod.YESTERDAY:
            previous_end = current_start
            previous_start = _midnight(
                current_start.date() - timedelta(days=1), zone
            )
        else:
            duration = current_end.astimezone(UTC) - current_start.astimezone(UTC)
            previous_end = current_start
            previous_start = (current_start.astimezone(UTC) - duration).astimezone(zone)

        day_count = (current_end.date() - current_start.date()).days + 1
        bucket = (
            TrendBucket.HOUR
            if period in {DashboardPeriod.TODAY, DashboardPeriod.YESTERDAY}
            else TrendBucket.DAY if day_count <= 31 else TrendBucket.WEEK
        )
        return ResolvedPeriod(
            period,
            timezone,
            DateTimeRange(current_start.astimezone(UTC), current_end.astimezone(UTC)),
            DateTimeRange(previous_start.astimezone(UTC), previous_end.astimezone(UTC)),
            bucket,
        )

    def buckets(self, resolved: ResolvedPeriod) -> tuple[tuple[datetime, datetime], ...]:
        zone = ZoneInfo(resolved.timezone)
        start = resolved.current.date_from.astimezone(zone)
        end = resolved.current.date_to.astimezone(zone)
        if resolved.bucket is TrendBucket.HOUR:
            cursor_utc = resolved.current.date_from
            values = []
            while cursor_utc < resolved.current.date_to:
                next_cursor = min(
                    cursor_utc + timedelta(hours=1), resolved.current.date_to
                )
                values.append((cursor_utc, next_cursor))
                cursor_utc = next_cursor
            return tuple(values)
        step = {
            TrendBucket.DAY: timedelta(days=1),
            TrendBucket.WEEK: timedelta(days=7),
        }[resolved.bucket]
        values: list[tuple[datetime, datetime]] = []
        cursor = start
        while cursor < end:
            next_cursor = min(cursor + step, end)
            values.append((cursor.astimezone(UTC), next_cursor.astimezone(UTC)))
            cursor = next_cursor
        return tuple(values)


def _midnight(value: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, time.min, zone)
