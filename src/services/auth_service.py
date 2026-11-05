"""Customer registration, email verification, and revocable bearer sessions."""
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from src.config import settings
from src.services.database import get_connection

_PASSWORD_SCRYPT_N = 2**14
_VERIFICATION_MINUTES = 10
_MAX_VERIFICATION_ATTEMPTS = 5


class EmailDeliveryError(RuntimeError):
    """Raised when the verification code cannot be delivered."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Enter a valid email address.")
    return value


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_PASSWORD_SCRYPT_N,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=_PASSWORD_SCRYPT_N,
            r=8,
            p=1,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _verification_digest(email: str, code: str) -> str:
    _require_auth_config()
    value = f"{email}:{code}".encode("utf-8")
    return hmac.new(settings.auth_secret_key.encode("utf-8"), value, hashlib.sha256).hexdigest()


def _require_auth_config() -> None:
    if len(settings.auth_secret_key) < 32:
        raise RuntimeError("AUTH_SECRET_KEY must contain at least 32 characters.")


def _send_verification_email(email: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_sender:
        raise EmailDeliveryError(
            "Email verification is unavailable. Configure SMTP_HOST and SMTP_SENDER."
        )
    message = EmailMessage()
    message["Subject"] = "Verify your ShopAssist account"
    message["From"] = settings.smtp_sender
    message["To"] = email
    message.set_content(
        f"Your ShopAssist verification code is {code}. "
        f"It expires in {_VERIFICATION_MINUTES} minutes."
    )
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Could not send the verification email.") from exc


class AuthService:
    """SQLite-backed customer identity and session management."""

    def register(self, email: str, full_name: str, password: str) -> None:
        email = _normalize_email(email)
        full_name = full_name.strip()
        if not full_name or len(full_name) > 120:
            raise ValueError("Full name must be between 1 and 120 characters.")
        if len(password) < 10 or len(password) > 128:
            raise ValueError("Password must be between 10 and 128 characters.")
        _verification_digest(email, "000000")

        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT verified_at, verification_sent_at FROM customers
                   WHERE email = ?""",
                (email,),
            ).fetchone()
            if existing and existing["verified_at"]:
                conn.commit()
                return
            if existing and existing["verification_sent_at"]:
                last_sent = datetime.fromisoformat(existing["verification_sent_at"])
                if _utcnow() - last_sent < timedelta(seconds=60):
                    conn.commit()
                    return

            code = f"{secrets.randbelow(1_000_000):06d}"
            expires = (_utcnow() + timedelta(minutes=_VERIFICATION_MINUTES)).isoformat()
            now = _utcnow().isoformat()
            if existing:
                conn.execute(
                    """UPDATE customers SET full_name = ?, password_hash = ?,
                       verification_hash = ?, verification_expires = ?,
                       verification_sent_at = ?, verification_attempts = 0
                       WHERE email = ?""",
                    (
                        full_name,
                        _password_hash(password),
                        _verification_digest(email, code),
                        expires,
                        now,
                        email,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO customers
                       (email, full_name, password_hash, verification_hash,
                        verification_expires, verification_sent_at,
                        verification_attempts, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                    (
                        email,
                        full_name,
                        _password_hash(password),
                        _verification_digest(email, code),
                        expires,
                        now,
                        now,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        try:
            _send_verification_email(email, code)
        except EmailDeliveryError:
            conn = get_connection()
            try:
                conn.execute(
                    """UPDATE customers SET verification_sent_at = NULL
                       WHERE email = ? AND verified_at IS NULL
                       AND verification_hash = ?""",
                    (email, _verification_digest(email, code)),
                )
                conn.commit()
            finally:
                conn.close()
            raise

    def verify_email(self, email: str, code: str) -> None:
        email = _normalize_email(email)
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("Verification code must contain six digits.")
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            customer = conn.execute(
                "SELECT * FROM customers WHERE email = ?", (email,)
            ).fetchone()
            if not customer:
                raise ValueError("Invalid or expired verification code.")
            if customer["verified_at"]:
                conn.commit()
                return
            if not customer["verification_hash"] or not customer["verification_expires"]:
                raise ValueError("Invalid or expired verification code.")
            expires = datetime.fromisoformat(customer["verification_expires"])
            if expires <= _utcnow() or customer["verification_attempts"] >= _MAX_VERIFICATION_ATTEMPTS:
                raise ValueError("Invalid or expired verification code.")

            supplied = _verification_digest(email, code)
            if not hmac.compare_digest(supplied, customer["verification_hash"]):
                attempts = customer["verification_attempts"] + 1
                conn.execute(
                    """UPDATE customers SET verification_attempts = ?,
                       verification_hash = CASE WHEN ? >= ? THEN NULL ELSE verification_hash END
                       WHERE email = ?""",
                    (attempts, attempts, _MAX_VERIFICATION_ATTEMPTS, email),
                )
                conn.commit()
                raise ValueError("Invalid or expired verification code.")

            conn.execute(
                """UPDATE customers SET verified_at = ?, verification_hash = NULL,
                   verification_expires = NULL, verification_sent_at = NULL,
                   verification_attempts = 0
                   WHERE email = ?""",
                (_utcnow().isoformat(), email),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def login(self, email: str, password: str) -> tuple[str, str, str]:
        _require_auth_config()
        email = _normalize_email(email)
        conn = get_connection()
        try:
            customer = conn.execute(
                "SELECT * FROM customers WHERE email = ?", (email,)
            ).fetchone()
            if not customer or not _verify_password(password, customer["password_hash"]):
                raise PermissionError("Invalid email or password.")
            if not customer["verified_at"]:
                raise PermissionError("Verify your email address before signing in.")

            token = secrets.token_urlsafe(32)
            expires_at = _utcnow() + timedelta(hours=settings.auth_session_hours)
            conn.execute(
                """INSERT INTO auth_sessions (token_hash, email, expires_at, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    hashlib.sha256(token.encode("ascii")).hexdigest(),
                    email,
                    expires_at.isoformat(),
                    _utcnow().isoformat(),
                ),
            )
            conn.commit()
            return token, customer["full_name"], expires_at.isoformat()
        finally:
            conn.close()

    def get_customer_for_token(self, token: str) -> dict | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT c.email, c.full_name, s.expires_at
                   FROM auth_sessions s JOIN customers c ON c.email = s.email
                   WHERE s.token_hash = ? AND s.revoked_at IS NULL""",
                (token_hash,),
            ).fetchone()
            if not row or datetime.fromisoformat(row["expires_at"]) <= _utcnow():
                return None
            return dict(row)
        finally:
            conn.close()

    def logout(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE auth_sessions SET revoked_at = ?
                   WHERE token_hash = ? AND revoked_at IS NULL""",
                (_utcnow().isoformat(), token_hash),
            )
            conn.commit()
        finally:
            conn.close()
