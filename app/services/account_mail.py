"""Account email delivery. Development messages are private files, never logs.

The disabled/file/SMTP backend is selected by settings. File delivery is a
private development artifact, not proof of SMTP delivery. Feature services own
token or outbox state; this adapter only delivers the supplied message.
"""

import smtplib
import ssl
import uuid
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings
from app.core.public_urls import public_site_ready, public_url


class MailUnavailable(ValueError):
    pass


def mail_available() -> bool:
    return (settings.account_mail_backend == "smtp" and public_site_ready()) or (
        settings.account_mail_backend == "file" and settings.environment == "development"
    )


def send_account_mail(recipient: str, purpose: str, token: str) -> None:
    if not mail_available():
        raise MailUnavailable("Email delivery is unavailable. Please try again later.")
    reset = purpose == "reset"
    path = "reset-password" if reset else "verify-email"
    link = public_url(f"/auth/{path}#token={token}")
    message = EmailMessage()
    message["From"] = settings.smtp_from or "Nurse.ng <no-reply@localhost>"
    message["To"] = recipient
    message["Subject"] = "Reset your Nurse.ng password" if reset else "Verify your Nurse.ng email"
    action = "reset your password" if reset else "verify your email address"
    lifetime = "30 minutes" if reset else "24 hours"
    message.set_content(
        f"Open this link to {action}:\n\n{link}\n\n"
        f"This link expires in {lifetime} and works once.\n"
        f"If you need to enter the code manually, use:\n{token}\n\n"
        "If you did not request this, you can ignore this email. "
        "Your password has not changed.\n"
    )
    deliver_mail(message)


def deliver_mail(message: EmailMessage) -> None:
    """Shared verified-TLS transport; caller decides content and retry policy."""
    if not mail_available():
        raise MailUnavailable("Email delivery is unavailable. Please try again later.")
    try:
        if settings.account_mail_backend == "file":
            root = Path(settings.account_mail_dir)
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root.chmod(0o700)
            path = root / f"{uuid.uuid4().hex}.eml"
            # Exclusive creation with restrictive permissions from the first write.
            import os

            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(message.as_bytes())
            return
        context = ssl.create_default_context()
        if settings.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=10,
                context=context,
            )
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=context)
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        # Do not expose provider replies, addresses or credentials in responses/logs.
        raise MailUnavailable("Email delivery is unavailable. Please try again later.") from None
