from functools import lru_cache

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


@lru_cache
def dummy_password_hash() -> str:
    return hash_password("not-a-real-user-password")
