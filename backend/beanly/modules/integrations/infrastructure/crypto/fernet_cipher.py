from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from beanly.modules.integrations.domain.exceptions import InvalidCredentials


class FernetSecretCipher:
    """Encrypts with the first key and decrypts with every configured rotation key."""

    def __init__(self, keys: list[str] | tuple[str, ...]) -> None:
        if not keys:
            raise ValueError("At least one integration encryption key is required")
        try:
            self._fernets = tuple(Fernet(key.encode()) for key in keys)
        except (TypeError, ValueError) as exc:
            raise ValueError("INTEGRATION_ENCRYPTION_KEYS contains an invalid Fernet key") from exc
        self._cipher = MultiFernet(list(self._fernets))

    @property
    def key_version(self) -> int:
        return 1

    def encrypt(self, value: bytes) -> str:
        return self._cipher.encrypt(value).decode()

    def decrypt(self, value: str) -> bytes:
        try:
            return self._cipher.decrypt(value.encode())
        except InvalidToken as exc:
            raise InvalidCredentials("Integration credentials cannot be decrypted") from exc

    def rotate(self, value: str) -> str:
        try:
            return self._cipher.rotate(value.encode()).decode()
        except InvalidToken as exc:
            raise InvalidCredentials("Integration credentials cannot be decrypted") from exc
