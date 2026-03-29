from .repository import Repository
from .models import Trade, Position, SignalRecord, RiskEvent


def create_repository() -> Repository:
    """Create the appropriate repository based on settings.

    If SUPABASE_DB_URL is configured, uses Supabase (asyncpg).
    Otherwise, falls back to local SQLite using DB_PATH.
    """
    from config import get_settings

    settings = get_settings()

    if settings.SUPABASE_DB_URL:
        from .supabase import SupabaseRepository
        return SupabaseRepository()
    else:
        from .sqlite import SqliteRepository
        return SqliteRepository(settings.DB_PATH)
