"""数据库会话:缺省 SQLite 零依赖演示;docker-compose 下注入 PostgreSQL DATABASE_URL。"""
from __future__ import annotations

from threading import Lock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import auth_required, get_settings, sqlite_default_url
from ..tenant import current_user_id


class Base(DeclarativeBase):
    pass


@event.listens_for(Session, "after_begin")
def _set_postgres_tenant_on_transaction(db, _transaction, connection) -> None:
    """Reapply the tenant after every commit/rollback starts a transaction."""
    tenant = db.info.get("sparklearn_tenant_id")
    if tenant and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.current_user_id', :tenant, true)"),
            {"tenant": tenant},
        )


def _url() -> str:
    return get_settings().database_url or sqlite_default_url()


_engine = None
_SessionLocal = None
_initialized_engine = None
_init_lock = Lock()

TENANT_TABLES = (
    "assessment_sessions",
    "profiles",
    "notebooks",
    "resources",
    "conversation_messages",
    "path_plans",
    "event_logs",
    "quiz_attempts",
    "review_items",
    "user_assets",
    "external_tasks",
    "personalization_decisions",
    "demo_baselines",
)

_LEGACY_USER_FOREIGN_KEYS = (
    "resources",
    "conversation_messages",
    "path_plans",
    "event_logs",
    "quiz_attempts",
    "review_items",
)


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = _url()
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, **kw)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    global _initialized_engine
    from . import entities  # noqa: F401  确保模型注册
    engine = get_engine()
    if _initialized_engine is engine:
        return
    with _init_lock:
        if _initialized_engine is engine:
            return
        Base.metadata.create_all(engine)
        if engine.dialect.name == "postgresql":
            _apply_postgres_tenant_security(engine)
        _initialized_engine = engine


def _apply_postgres_tenant_security(engine) -> None:
    """Idempotently enforce tenant ownership for every user-scoped table.

    Existing installations receive NOT VALID foreign keys so deployment does
    not fail on historical demo rows; PostgreSQL still validates all new data.
    Row-level policies fail closed when no request tenant is attached.
    """
    with engine.begin() as conn:
        for table in _LEGACY_USER_FOREIGN_KEYS:
            constraint = f"fk_{table}_user_id_users"
            conn.execute(text(f"""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        WHERE c.contype = 'f'
                          AND c.conrelid = '{table}'::regclass
                          AND c.confrelid = 'users'::regclass
                          AND c.conkey = ARRAY[(
                              SELECT attnum FROM pg_attribute
                              WHERE attrelid = '{table}'::regclass
                                AND attname = 'user_id'
                          )]
                    ) THEN
                        ALTER TABLE {table}
                        ADD CONSTRAINT {constraint}
                        FOREIGN KEY (user_id) REFERENCES users(id)
                        ON DELETE CASCADE NOT VALID;
                    END IF;
                END $$;
            """))

        tenant_expr = (
            "user_id = NULLIF(current_setting('app.current_user_id', true), '')"
        )
        for table in TENANT_TABLES:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies
                        WHERE schemaname = current_schema()
                          AND tablename = '{table}'
                          AND policyname = 'sparklearn_tenant_isolation'
                    ) THEN
                        CREATE POLICY sparklearn_tenant_isolation ON {table}
                        USING ({tenant_expr})
                        WITH CHECK ({tenant_expr});
                    END IF;
                END $$;
            """))


def session() -> Session:
    engine = get_engine()
    db = _SessionLocal()
    if engine.dialect.name == "postgresql":
        tenant = current_user_id()
        if not tenant and not auth_required():
            tenant = "demo_user"
        if tenant:
            db.info["sparklearn_tenant_id"] = tenant
    return db
