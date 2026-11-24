"""Password hashing. Argon2 via pwdlib's recommended configuration.

Use these primitives through the authentication/account services. Passwords
are hashed, never encrypted for later recovery; reset uses single-use tokens.
"""

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Create an Argon2 password hash for storage; never persist the supplied plaintext."""
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Compare supplied plaintext to a saved hash using the configured password verifier."""
    return _password_hash.verify(password, hashed_password)
