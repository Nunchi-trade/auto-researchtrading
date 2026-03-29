# Backward compatibility — use storage.repository.Repository or storage.create_repository() instead.
from .supabase import SupabaseRepository as Database

__all__ = ["Database"]
