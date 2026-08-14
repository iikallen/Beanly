"""Cash management, register reconciliation and close of day.

Revision ID: 0026_cash_management
Revises: 0025_customers_crm_loyalty
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0026_cash_management"
down_revision = "0025_customers_crm_loyalty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_register_shifts_open_register", table_name="register_shifts")
    op.drop_constraint("ck_register_shift_status", "register_shifts", type_="check")
    op.create_check_constraint(
        "ck_register_shift_status", "register_shifts", "status IN ('OPEN','CLOSING','CLOSED')"
    )
    op.create_index(
        "uq_register_shifts_open_register",
        "register_shifts",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN','CLOSING')"),
        sqlite_where=sa.text("status IN ('OPEN','CLOSING')"),
    )
    op.add_column(
        "locations",
        sa.Column(
            "cash_variance_approval_threshold_minor",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_location_cash_variance_threshold",
        "locations",
        "cash_variance_approval_threshold_minor >= 0",
    )
    op.create_table(
        "cash_drawer_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "shift_id",
            sa.Uuid(),
            sa.ForeignKey("register_shifts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("starting_cash_minor", sa.BigInteger(), nullable=False),
        sa.Column("expected_cash_minor_snapshot", sa.BigInteger()),
        sa.Column("actual_cash_minor", sa.BigInteger()),
        sa.Column("variance_minor", sa.BigInteger()),
        sa.Column("opened_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("close_note", sa.Text()),
        sa.Column("client_open_id", sa.Uuid(), nullable=False),
        sa.Column("client_close_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("shift_id", name="uq_cash_drawer_shift"),
        sa.UniqueConstraint("organization_id", "client_open_id", name="uq_cash_drawer_client_open"),
        sa.CheckConstraint("status IN ('OPEN','CLOSING','CLOSED')", name="ck_cash_drawer_status"),
        sa.CheckConstraint("starting_cash_minor >= 0", name="ck_cash_drawer_starting"),
        sa.CheckConstraint("length(currency_code) = 3", name="ck_cash_drawer_currency"),
        sa.CheckConstraint("version > 0", name="ck_cash_drawer_version"),
    )
    op.create_index(
        "ix_cash_drawer_sessions_organization_id", "cash_drawer_sessions", ["organization_id"]
    )
    op.create_index("ix_cash_drawer_sessions_location_id", "cash_drawer_sessions", ["location_id"])
    op.create_index("ix_cash_drawer_sessions_register_id", "cash_drawer_sessions", ["register_id"])
    op.create_index("ix_cash_drawer_sessions_status", "cash_drawer_sessions", ["status"])
    op.create_index(
        "ix_cash_drawer_org_opened", "cash_drawer_sessions", ["organization_id", "opened_at"]
    )
    op.create_index(
        "ix_cash_drawer_location_status", "cash_drawer_sessions", ["location_id", "status"]
    )
    op.create_index(
        "uq_cash_drawer_active_register",
        "cash_drawer_sessions",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN','CLOSING')"),
        sqlite_where=sa.text("status IN ('OPEN','CLOSING')"),
    )
    op.create_table(
        "cash_drawer_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drawer_session_id",
            sa.Uuid(),
            sa.ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_line_id", sa.Uuid(), nullable=False),
        sa.Column("client_movement_id", sa.Uuid()),
        sa.Column("reason", sa.String(1000)),
        sa.Column("note", sa.Text()),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "source_type",
            "source_id",
            "source_line_id",
            name="uq_cash_drawer_movement_source",
        ),
        sa.UniqueConstraint(
            "organization_id", "client_movement_id", name="uq_cash_drawer_movement_client"
        ),
        sa.CheckConstraint(
            "kind IN ('OPENING_FLOAT','CASH_PAYMENT','CASH_REFUND','PAY_IN','PAY_OUT')",
            name="ck_cash_drawer_movement_kind",
        ),
        sa.CheckConstraint(
            "amount_minor <> 0 OR kind = 'OPENING_FLOAT'", name="ck_cash_drawer_movement_amount"
        ),
    )
    op.create_index(
        "ix_cash_drawer_movements_organization_id", "cash_drawer_movements", ["organization_id"]
    )
    op.create_index(
        "ix_cash_drawer_movements_drawer_session_id", "cash_drawer_movements", ["drawer_session_id"]
    )
    op.create_index(
        "ix_cash_drawer_movement_session_time",
        "cash_drawer_movements",
        ["drawer_session_id", "occurred_at"],
    )
    op.create_table(
        "cash_drawer_close_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drawer_session_id",
            sa.Uuid(),
            sa.ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starting_cash_minor", sa.BigInteger(), nullable=False),
        sa.Column("cash_payments_minor", sa.BigInteger(), nullable=False),
        sa.Column("cash_refunds_minor", sa.BigInteger(), nullable=False),
        sa.Column("pay_in_minor", sa.BigInteger(), nullable=False),
        sa.Column("pay_out_minor", sa.BigInteger(), nullable=False),
        sa.Column("expected_cash_minor", sa.BigInteger(), nullable=False),
        sa.Column("actual_cash_minor", sa.BigInteger(), nullable=False),
        sa.Column("variance_minor", sa.BigInteger(), nullable=False),
        sa.Column("approval_threshold_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("drawer_session_id", name="uq_cash_drawer_close_snapshot"),
        sa.CheckConstraint("actual_cash_minor >= 0", name="ck_cash_close_actual"),
    )
    op.create_index(
        "ix_cash_drawer_close_snapshots_organization_id",
        "cash_drawer_close_snapshots",
        ["organization_id"],
    )
    op.create_table(
        "cash_drawer_fiscal_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drawer_session_id",
            sa.Uuid(),
            sa.ForeignKey("cash_drawer_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fiscal_job_id", sa.Uuid(), sa.ForeignKey("integration_jobs.id")),
        sa.Column("status", sa.String(32), nullable=False, server_default="NOT_REQUIRED"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("drawer_session_id", name="uq_cash_drawer_fiscal_state"),
    )
    op.create_index(
        "ix_cash_drawer_fiscal_states_organization_id",
        "cash_drawer_fiscal_states",
        ["organization_id"],
    )
    _backfill_legacy_shifts()
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION prevent_cash_ledger_mutation() RETURNS trigger AS $$ BEGIN IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM organizations WHERE id = OLD.organization_id) THEN RETURN OLD; END IF; RAISE EXCEPTION 'cash ledger is immutable'; END; $$ LANGUAGE plpgsql"  # noqa: E501
        )
        op.execute(
            "CREATE TRIGGER trg_cash_movement_immutable BEFORE UPDATE OR DELETE ON cash_drawer_movements FOR EACH ROW EXECUTE FUNCTION prevent_cash_ledger_mutation()"  # noqa: E501
        )
        op.execute(
            "CREATE TRIGGER trg_cash_close_snapshot_immutable BEFORE UPDATE OR DELETE ON cash_drawer_close_snapshots FOR EACH ROW EXECUTE FUNCTION prevent_cash_ledger_mutation()"  # noqa: E501
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_cash_close_snapshot_immutable ON cash_drawer_close_snapshots"  # noqa: E501
        )
        op.execute("DROP TRIGGER IF EXISTS trg_cash_movement_immutable ON cash_drawer_movements")
        op.execute("DROP FUNCTION IF EXISTS prevent_cash_ledger_mutation()")
    op.drop_table("cash_drawer_fiscal_states")
    op.drop_table("cash_drawer_close_snapshots")
    op.drop_table("cash_drawer_movements")
    op.drop_table("cash_drawer_sessions")
    op.drop_constraint("ck_location_cash_variance_threshold", "locations", type_="check")
    op.drop_column("locations", "cash_variance_approval_threshold_minor")
    op.drop_index("uq_register_shifts_open_register", table_name="register_shifts")
    op.drop_constraint("ck_register_shift_status", "register_shifts", type_="check")
    op.execute("UPDATE register_shifts SET status = 'OPEN' WHERE status = 'CLOSING'")
    op.create_check_constraint(
        "ck_register_shift_status", "register_shifts", "status IN ('OPEN','CLOSED')"
    )
    op.create_index(
        "uq_register_shifts_open_register",
        "register_shifts",
        ["register_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )


def _backfill_legacy_shifts() -> None:
    connection = op.get_bind()
    shifts = (
        connection.execute(
            sa.text(
                "SELECT s.id,s.organization_id,s.location_id,s.register_id,s.status,s.opened_by_user_id,"  # noqa: E501
                "s.closed_by_user_id,s.opened_at,s.closed_at,s.created_at,s.updated_at,o.currency_code "  # noqa: E501
                "FROM register_shifts s JOIN organizations o ON o.id=s.organization_id"
            )
        )
        .mappings()
        .all()
    )
    for shift in shifts:
        shift_id = shift["id"]
        drawer_id = uuid.uuid5(uuid.NAMESPACE_URL, f"beanly:legacy-drawer:{shift_id}")
        opening_id = uuid.uuid5(uuid.NAMESPACE_URL, f"beanly:legacy-opening:{shift_id}")
        connection.execute(
            sa.text(
                "INSERT INTO cash_drawer_sessions "
                "(id,organization_id,location_id,register_id,shift_id,currency_code,status,starting_cash_minor,"  # noqa: E501
                "expected_cash_minor_snapshot,actual_cash_minor,variance_minor,opened_by_user_id,opened_at,"  # noqa: E501
                "closed_by_user_id,closed_at,approved_by_user_id,approved_at,close_note,client_open_id,"  # noqa: E501
                "client_close_id,created_at,updated_at,version) VALUES "
                "(:id,:org,:location,:register,:shift,:currency,:status,0,:expected,:actual,:variance,:opened_by,"  # noqa: E501
                ":opened_at,:closed_by,:closed_at,NULL,NULL,:note,:client_open,:client_close,:created_at,:updated_at,1)"  # noqa: E501
            ),
            {
                "id": drawer_id,
                "org": shift["organization_id"],
                "location": shift["location_id"],
                "register": shift["register_id"],
                "shift": shift_id,
                "currency": shift["currency_code"],
                "status": shift["status"],
                "expected": 0 if shift["status"] == "CLOSED" else None,
                "actual": 0 if shift["status"] == "CLOSED" else None,
                "variance": 0 if shift["status"] == "CLOSED" else None,
                "opened_by": shift["opened_by_user_id"],
                "opened_at": shift["opened_at"],
                "closed_by": shift["closed_by_user_id"],
                "closed_at": shift["closed_at"],
                "note": "Legacy shift backfill" if shift["status"] == "CLOSED" else None,
                "client_open": shift_id,
                "client_close": shift_id if shift["status"] == "CLOSED" else None,
                "created_at": shift["created_at"],
                "updated_at": shift["updated_at"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO cash_drawer_movements "
                "(id,organization_id,drawer_session_id,kind,amount_minor,source_type,source_id,source_line_id,"  # noqa: E501
                "client_movement_id,reason,note,created_by_user_id,occurred_at,recorded_at) VALUES "
                "(:id,:org,:drawer,'OPENING_FLOAT',0,'SHIFT_OPEN',:shift,:drawer,NULL,'Legacy opening float',NULL,"  # noqa: E501
                ":actor,:occurred,:recorded)"
            ),
            {
                "id": opening_id,
                "org": shift["organization_id"],
                "drawer": drawer_id,
                "shift": shift_id,
                "actor": shift["opened_by_user_id"],
                "occurred": shift["opened_at"],
                "recorded": shift["created_at"],
            },
        )
        if shift["status"] == "CLOSED":
            snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, f"beanly:legacy-close:{shift_id}")
            fiscal_state_id = uuid.uuid5(uuid.NAMESPACE_URL, f"beanly:legacy-fiscal:{shift_id}")
            connection.execute(
                sa.text(
                    "INSERT INTO cash_drawer_close_snapshots "
                    "(id,organization_id,drawer_session_id,starting_cash_minor,cash_payments_minor,"
                    "cash_refunds_minor,pay_in_minor,pay_out_minor,expected_cash_minor,actual_cash_minor,"  # noqa: E501
                    "variance_minor,approval_threshold_minor,created_at) VALUES "
                    "(:id,:org,:drawer,0,0,0,0,0,0,0,0,0,:created)"
                ),
                {
                    "id": snapshot_id,
                    "org": shift["organization_id"],
                    "drawer": drawer_id,
                    "created": shift["closed_at"] or shift["updated_at"],
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO cash_drawer_fiscal_states "
                    "(id,organization_id,drawer_session_id,fiscal_job_id,status,updated_at) VALUES "
                    "(:id,:org,:drawer,NULL,'NOT_REQUIRED',:updated)"
                ),
                {
                    "id": fiscal_state_id,
                    "org": shift["organization_id"],
                    "drawer": drawer_id,
                    "updated": shift["closed_at"] or shift["updated_at"],
                },
            )
