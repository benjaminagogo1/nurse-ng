"""Exercise account recovery, photo privacy, session revocation and deletion."""

import hashlib
import re
import uuid
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.config import settings
from app.models.account import AccountToken, FileDeletion
from app.models.community import CommunityMedia, CommunityPost, CommunityReply, CommunityTopic
from app.models.jobs import Job, JobApplication
from app.models.messages import DirectMessage
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import EvidenceDocument, VerificationCase
from app.services import accounts
from app.services.account_mail import send_account_mail
from app.services.auth import AuthError, register_user, save_account_details
from tests.helpers import csrf_from, has_element

PASSWORD = "original-password"
NEW_PASSWORD = "my-new-secure-password"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    for setting, directory in [
        ("avatar_dir", "avatars"),
        ("evidence_dir", "evidence"),
        ("community_media_dir", "community"),
        ("account_mail_dir", "mail"),
    ]:
        monkeypatch.setattr(settings, setting, str(tmp_path / directory))
    monkeypatch.setattr(settings, "account_mail_backend", "file")
    monkeypatch.setattr(settings, "public_base_url", "https://nurse.example")


@pytest.fixture
def member(db_session):
    return register_user(
        db_session,
        phone="+2348000000051",
        password=PASSWORD,
        full_name="Ada Example",
        email="ada@example.org",
    )


def login(client, member, password=PASSWORD):
    response = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_from(client.get("/auth/login")),
            "phone": member.phone,
            "password": password,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def photo():
    result = BytesIO()
    image = Image.new("RGB", (600, 400), "green")
    exif = Image.Exif()
    exif[315] = "private camera owner"
    image.save(result, "JPEG", exif=exif)
    return result.getvalue()


def token_from_email():
    path = max(Path(settings.account_mail_dir).glob("*.eml"), key=lambda p: p.stat().st_mtime_ns)
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    token = re.search(r"#token=([A-Za-z0-9_-]{43})", message.get_content()).group(1)
    assert path.stat().st_mode & 0o777 == 0o600
    return token, message


def release_mail_cooldown(db, member):
    member.account_mail_requested_at = accounts.now() - timedelta(minutes=2)
    db.commit()


def verify_email(db, member):
    assert accounts.request_account_email(db, purpose="verify", user=member)
    token, _ = token_from_email()
    accounts.consume_account_token(db, token, "verify")
    release_mail_cooldown(db, member)


def test_photo_upload_private_then_public_replacement_and_removal(client, db_session, member):
    login(client, member)
    token = csrf_from(client.get("/settings"))
    assert client.post("/settings/photo", files={"photo": ("me.jpg", photo())}).status_code == 400
    response = client.post(
        "/settings/photo",
        data={"csrf_token": token},
        files={"photo": ("me.jpg", photo())},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(member)
    first = member.photo_storage_name
    stored = Image.open(accounts.avatar_path(first))
    assert stored.size == (512, 512) and not stored.getexif()
    own_cookie = dict(client.cookies)
    url = "/account/photos/" + first
    response = client.get(url)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert url in client.get("/settings").text
    client.cookies.clear()
    assert client.get(url).status_code == 404
    client.cookies.update(own_cookie)
    assert (
        client.post(
            "/settings/photo/visibility",
            data={
                "csrf_token": token,
                "public": "true",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    client.cookies.clear()
    assert client.get(url).status_code == 200
    client.cookies.update(own_cookie)
    client.post(
        "/settings/photo",
        data={"csrf_token": token, "public": "true"},
        files={"photo": ("replacement.jpg", photo())},
    )
    db_session.refresh(member)
    assert member.photo_storage_name != first
    assert not accounts.avatar_path(first).exists() and client.get(url).status_code == 404
    current = member.photo_storage_name
    client.post("/settings/photo/remove", data={"csrf_token": token})
    db_session.refresh(member)
    assert not member.photo_storage_name and not accounts.avatar_path(current).exists()


def test_feedback_confirms_saved_changes_once_and_keeps_errors_separate(client, db_session, member):
    login(client, member)
    assert "Profile photo updated" not in client.get("/settings?photo=saved&saved=1").text
    csrf = csrf_from(client.get("/settings"))
    response = client.post(
        "/settings/photo", headers={"X-Account-Feedback": "1"},
        data={"csrf_token": csrf}, files={"photo": ("me.jpg", photo())},
    )
    assert response.status_code == 200 and response.json() == {"redirect": "/settings"}
    db_session.refresh(member)
    assert member.photo_storage_name
    # Unrelated reads cannot consume an operation's confirmation.
    client.get("/auth/dashboard")
    confirmed = client.get("/settings")
    assert "Profile photo updated" in confirmed.text
    assert 'class="action-feedback action-feedback--success"' in confirmed.text
    assert "Profile photo updated" not in client.get("/settings").text
    original = member.photo_storage_name
    failed = client.post(
        "/settings/photo", headers={"X-Account-Feedback": "1"},
        data={"csrf_token": csrf}, files={"photo": ("invalid.jpg", b"invalid")},
    )
    assert failed.status_code == 400
    assert failed.json()["feedback"]["tone"] == "error"
    assert "photo" in failed.json()["feedback"]["fields"]
    assert "redirect" not in failed.json()
    db_session.refresh(member)
    assert member.photo_storage_name == original


def test_reset_confirmation_survives_session_revocation_without_query_flags(
    client, db_session, member
):
    assert "Password updated" not in client.get("/auth/login?reset=1&deleted=1").text
    verify_email(db_session, member)
    accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    token, _ = token_from_email()
    login(client, member)
    response = client.post(
        "/auth/reset-password", headers={"X-Account-Feedback": "1"},
        data={"csrf_token": csrf_from(client.get("/auth/reset-password")), "token": token,
              "password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
    )
    assert response.json() == {"redirect": "/auth/login"}
    page = client.get("/auth/login")
    assert "Password updated" in page.text and "previous sign-in sessions have ended" in page.text
    assert has_element(page, 'input', name='password', type='password')
    assert NEW_PASSWORD not in page.text and token not in page.text
    assert "Password updated" not in client.get("/auth/login").text
    assert client.get("/settings", follow_redirects=False).status_code == 303


def test_verified_account_gets_truthful_feedback_without_another_email(client, db_session, member):
    verify_email(db_session, member)
    before = list(Path(settings.account_mail_dir).glob("*.eml"))
    login(client, member)
    result = client.post("/settings/verify-email", data={
        "csrf_token": csrf_from(client.get("/settings")),
    })
    assert "Email already verified" in result.text
    assert 'account-status--success' in result.text
    assert list(Path(settings.account_mail_dir).glob("*.eml")) == before


@pytest.mark.parametrize("data", [b"", b"<svg><script>alert(1)</script></svg>", b"fake jpeg"])
def test_invalid_photo_keeps_previous_photo(db_session, member, data):
    accounts.set_photo(db_session, member, data=photo())
    original = member.photo_storage_name
    with pytest.raises(AuthError):
        accounts.set_photo(db_session, member, data=data)
    assert member.photo_storage_name == original and accounts.avatar_path(original).exists()


def test_photo_limits_and_cross_account_privacy(client, db_session, member, monkeypatch):
    accounts.set_photo(db_session, member, data=photo())
    other = register_user(db_session, phone="+2348000000052", password=PASSWORD)
    login(client, other)
    assert client.get("/account/photos/" + member.photo_storage_name).status_code == 404
    monkeypatch.setattr(settings, "avatar_max_bytes", 100)
    assert (
        client.post(
            "/settings/photo",
            data={"csrf_token": csrf_from(client.get("/settings"))},
            files={"photo": ("big.jpg", photo())},
        ).status_code
        == 400
    )
    assert not other.photo_storage_name


def test_email_verification_and_recovery_revoke_existing_sessions(client, db_session, member):
    login(client, member)
    assert "Protect access to your account" in client.get("/auth/dashboard").text
    cookies_before_reset = dict(client.cookies)
    verify_response = client.post(
        "/settings/verify-email",
        data={
            "csrf_token": csrf_from(client.get("/settings")),
        },
    )
    assert verify_response.status_code == 200
    verify_token, message = token_from_email()
    assert "https://nurse.example/auth/verify-email#token=" in message.get_content()
    row = db_session.scalar(select(AccountToken))
    assert row.token_hash == hashlib.sha256(verify_token.encode()).hexdigest()
    assert verify_token not in row.token_hash
    client.cookies.clear()
    response = client.post(
        "/auth/verify-email",
        data={
            "csrf_token": csrf_from(client.get("/auth/verify-email")),
            "token": verify_token,
        },
    )
    assert response.status_code == 200 and "Email verified" in response.text
    db_session.refresh(member)
    assert member.email_verified_at
    release_mail_cooldown(db_session, member)
    response = client.post(
        "/auth/forgot-password",
        data={
            "csrf_token": csrf_from(client.get("/auth/forgot-password")),
            "phone": member.phone,
        },
    )
    assert response.status_code == 200
    reset_token, _ = token_from_email()
    response = client.post(
        "/auth/reset-password",
        data={
            "csrf_token": csrf_from(client.get("/auth/reset-password")),
            "token": reset_token,
            "password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(member)
    assert member.check_password(NEW_PASSWORD) and not member.check_password(PASSWORD)
    client.cookies.clear()
    client.cookies.update(cookies_before_reset)
    assert client.get("/settings", follow_redirects=False).status_code == 303
    login(client, member, NEW_PASSWORD)
    assert "Protect access to your account" not in client.get("/auth/dashboard").text
    with pytest.raises(AuthError, match="invalid or has expired"):
        accounts.consume_account_token(db_session, reset_token, "reset", password=NEW_PASSWORD)


def test_unverified_unknown_and_known_reset_responses_do_not_disclose_accounts(
    client,
    db_session,
    member,
):
    token = csrf_from(client.get("/auth/forgot-password"))
    unverified = client.post(
        "/auth/forgot-password", data={"csrf_token": token, "phone": member.phone}
    )
    assert not list(Path(settings.account_mail_dir).glob("*.eml"))
    unknown = client.post(
        "/auth/forgot-password", data={"csrf_token": token, "phone": "+2348000999999"}
    )
    assert unverified.text == unknown.text and unverified.status_code == unknown.status_code == 200
    verify_email(db_session, member)
    known = client.post("/auth/forgot-password", data={"csrf_token": token, "phone": member.phone})
    assert known.text == unknown.text


@pytest.mark.parametrize("change", ["expired", "email", "version", "inactive", "purpose"])
def test_invalid_recovery_credentials_never_change_password(db_session, member, change):
    verify_email(db_session, member)
    accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    token, _ = token_from_email()
    credential = db_session.scalar(select(AccountToken).where(AccountToken.purpose == "reset"))
    if change == "expired":
        credential.expires_at = accounts.now() - timedelta(seconds=1)
    elif change == "email":
        member.email = "changed@example.org"
    elif change == "version":
        member.auth_version += 1
    elif change == "inactive":
        member.is_active = False
    db_session.commit()
    with pytest.raises(AuthError):
        accounts.consume_account_token(
            db_session, token, "verify" if change == "purpose" else "reset", password=NEW_PASSWORD
        )
    db_session.refresh(member)
    assert member.check_password(PASSWORD)


def test_new_link_invalidates_old_link_and_cooldown_persists(db_session, member):
    verify_email(db_session, member)
    accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    first, _ = token_from_email()
    assert not accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    release_mail_cooldown(db_session, member)
    assert accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    second, _ = token_from_email()
    with pytest.raises(AuthError):
        accounts.consume_account_token(db_session, first, "reset", password=NEW_PASSWORD)
    accounts.consume_account_token(db_session, second, "reset", password=NEW_PASSWORD)


def test_email_changes_require_password_and_revoke_email_credentials(db_session, member):
    verify_email(db_session, member)
    accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    with pytest.raises(AuthError):
        save_account_details(db_session, member, full_name="Ada", email="new@example.org")
    assert member.email == "ada@example.org"
    save_account_details(
        db_session, member, full_name="Ada", email="new@example.org", current_password=PASSWORD
    )
    assert member.email_verified_at is None
    assert db_session.scalar(select(func.count()).select_from(AccountToken)) == 0


def test_recovery_csrf_validation_and_rate_limit(client, member):
    assert client.post("/auth/forgot-password", data={"phone": member.phone}).status_code == 400
    token = csrf_from(client.get("/auth/forgot-password"))
    for _ in range(5):
        assert (
            client.post(
                "/auth/forgot-password",
                data={
                    "csrf_token": token,
                    "phone": "+2348000999999",
                },
            ).status_code
            == 200
        )
    response = client.post(
        "/auth/forgot-password", data={"csrf_token": token, "phone": member.phone}
    )
    assert response.status_code == 429 and response.headers.get("retry-after")


def test_disabled_delivery_is_honest_and_creates_no_credentials(
    client, db_session, member, monkeypatch
):
    monkeypatch.setattr(settings, "account_mail_backend", "disabled")
    login(client, member)
    assert "Protect access to your account" not in client.get("/auth/dashboard").text
    page = client.get("/auth/forgot-password")
    assert "currently unavailable" in page.text
    response = client.post(
        "/auth/forgot-password",
        data={
            "csrf_token": csrf_from(client.get("/auth/login")),
            "phone": member.phone,
        },
    )
    assert response.status_code == 503 and db_session.scalar(select(AccountToken)) is None


def test_smtp_uses_verified_tls_and_configured_sender(monkeypatch):
    import ssl

    from app.services import account_mail

    calls = []

    class SMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.org", 587, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def starttls(self, context):
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            calls.append("tls")

        def login(self, username, password):
            assert calls == ["tls"]
            calls.append("login")

        def send_message(self, message):
            assert calls == ["tls", "login"]
            assert message["To"] == "ada@example.org"
            assert message["From"].addresses[0].addr_spec == "noreply@nurse.example"
            calls.append("sent")

    monkeypatch.setattr(account_mail.smtplib, "SMTP", SMTP)
    for key, value in {
        "account_mail_backend": "smtp",
        "smtp_host": "smtp.example.org",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "user",
        "smtp_password": "test-secret",
        "smtp_from": "Nurse.ng <noreply@nurse.example>",
    }.items():
        monkeypatch.setattr(settings, key, value)
    send_account_mail("ada@example.org", "reset", "x" * 43)
    assert calls == ["tls", "login", "sent"]


def test_account_deletion_removes_owned_rows_files_and_all_sessions(client, db_session, member):
    accounts.set_photo(db_session, member, data=photo(), public=True)
    avatar_name = member.photo_storage_name
    other = register_user(db_session, phone="+2348000000052", password=PASSWORD)
    profile = NurseProfile(user_id=member.id, display_name="Private name", status="active")
    topic = CommunityTopic(name="Deletion test", slug="deletion-test")
    db_session.add_all([profile, topic])
    db_session.flush()
    post = CommunityPost(author_id=member.id, topic_id=topic.id, body="Owned conversation")
    case = VerificationCase(profile_id=profile.id, registration_number="private-number")
    job = Job(employer_user_id=member.id, title="Owned job", organization="Private organisation")
    db_session.add_all([post, case, job])
    db_session.flush()
    evidence_name, media_name = uuid.uuid4().hex, uuid.uuid4().hex
    db_session.add_all(
        [
            CommunityReply(author_id=other.id, post_id=post.id, body="Reply within deleted thread"),
            CommunityMedia(
                post_id=post.id,
                storage_name=media_name,
                kind="image",
                content_type="image/jpeg",
                size_bytes=3,
            ),
            EvidenceDocument(
                case_id=case.id,
                kind="licence",
                storage_name=evidence_name,
                content_type="application/pdf",
                size_bytes=3,
                sha256="a" * 64,
            ),
            DirectMessage(sender_id=member.id, recipient_id=other.id, body="Private message"),
            JobApplication(
                job_id=job.id,
                applicant_user_id=other.id,
                candidate_name="Other",
                candidate_phone=other.phone,
            ),
        ]
    )
    db_session.commit()
    for root, name in [
        (settings.evidence_dir, evidence_name),
        (settings.community_media_dir, media_name),
    ]:
        Path(root).mkdir(parents=True, exist_ok=True)
        (Path(root) / name).write_bytes(b"abc")
    member_id, other_id, public_id = member.id, other.id, profile.public_id
    login(client, member)
    old_cookies = dict(client.cookies)
    token = csrf_from(client.get("/settings/delete-account"))
    assert (
        client.post(
            "/settings/delete-account",
            data={
                "password": PASSWORD,
                "confirmation": "DELETE",
            },
        ).status_code
        == 400
    )
    for payload in [
        {"password": "wrong", "confirmation": "DELETE"},
        {"password": PASSWORD, "confirmation": ""},
    ]:
        assert (
            client.post(
                "/settings/delete-account",
                data={
                    "csrf_token": token,
                    **payload,
                },
            ).status_code
            == 400
        )
        assert db_session.get(User, member_id) is not None
    response = client.post(
        "/settings/delete-account",
        data={
            "csrf_token": token,
            "password": PASSWORD,
            "confirmation": "DELETE",
            "user_id": str(other_id),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db_session.get(User, member_id) is None and db_session.get(User, other_id) is not None
    for model in [
        NurseProfile,
        CommunityPost,
        CommunityReply,
        CommunityMedia,
        VerificationCase,
        EvidenceDocument,
        DirectMessage,
        Job,
        JobApplication,
    ]:
        assert db_session.scalar(select(func.count()).select_from(model)) == 0, model
    assert not accounts.avatar_path(avatar_name).exists()
    assert not (Path(settings.evidence_dir) / evidence_name).exists()
    assert not (Path(settings.community_media_dir) / media_name).exists()
    client.cookies.update(old_cookies)
    assert client.get("/settings", follow_redirects=False).status_code == 303
    assert client.get(f"/p/{public_id}").status_code == 404
    assert client.get("/account/photos/" + avatar_name).status_code == 404


def test_failed_file_removal_is_durable_and_retryable(db_session, member, monkeypatch):
    accounts.set_photo(db_session, member, data=photo(), public=True)
    name = member.photo_storage_name
    original = Path.unlink

    def blocked(path, *args, **kwargs):
        if path.name == name:
            raise PermissionError("Temporary storage error")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked)
    accounts.delete_account(db_session, member, password=PASSWORD)
    assert db_session.scalar(select(FileDeletion)).storage_name == name
    assert accounts.avatar_path(name).exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert accounts.cleanup_account_files(db_session) == {"removed": 1}
    assert not accounts.avatar_path(name).exists()


def test_password_validation_keeps_reset_link_usable(client, db_session, member):
    verify_email(db_session, member)
    accounts.request_account_email(db_session, purpose="reset", phone=member.phone)
    token, _ = token_from_email()
    csrf = csrf_from(client.get("/auth/reset-password"))
    for password, confirmation in [(NEW_PASSWORD, "different"), ("short", "short")]:
        response = client.post(
            "/auth/reset-password",
            data={
                "csrf_token": csrf,
                "token": token,
                "password": password,
                "confirm_password": confirmation,
            },
        )
        assert response.status_code == 400
        db_session.refresh(member)
        assert member.check_password(PASSWORD)
    accounts.consume_account_token(db_session, token, "reset", password=NEW_PASSWORD)


def test_mail_failure_invalidates_token_without_disclosing_account(
    client,
    db_session,
    member,
    monkeypatch,
    caplog,
):
    from sqlalchemy.orm import sessionmaker

    from app.services.account_mail import MailUnavailable
    from app.web import account_routes

    verify_email(db_session, member)

    def fail(*args):
        raise MailUnavailable("provider-secret-and-address")

    monkeypatch.setattr(account_routes, "send_account_mail", fail)
    monkeypatch.setattr(account_routes, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    csrf = csrf_from(client.get("/auth/forgot-password"))
    known = client.post("/auth/forgot-password", data={"csrf_token": csrf, "phone": member.phone})
    unknown = client.post(
        "/auth/forgot-password",
        data={
            "csrf_token": csrf,
            "phone": "+2348000999999",
        },
    )
    assert known.status_code == unknown.status_code == 200 and known.text == unknown.text
    assert "provider-secret-and-address" not in caplog.text
    assert "delivery failed" in caplog.text
    assert db_session.scalar(select(AccountToken).where(AccountToken.purpose == "reset")) is None


def test_deletion_preserves_other_members_content_and_staff_decisions(db_session, member):
    other = register_user(db_session, phone="+2348000000052", password=PASSWORD)
    topic = CommunityTopic(name="Other topic", slug="other-topic")
    profile = NurseProfile(user_id=other.id)
    db_session.add_all([topic, profile])
    db_session.flush()
    post = CommunityPost(author_id=other.id, topic_id=topic.id, body="Keep this content")
    case = VerificationCase(
        profile_id=profile.id,
        registration_number="keep-this",
        decided_by_user_id=member.id,
        decision_note="Reviewed",
    )
    db_session.add_all([post, case])
    db_session.flush()
    name = uuid.uuid4().hex
    media = CommunityMedia(
        post_id=post.id, storage_name=name, kind="image", content_type="image/jpeg", size_bytes=3
    )
    db_session.add(media)
    db_session.commit()
    path = Path(settings.community_media_dir) / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"abc")
    post_id, case_id, media_id = post.id, case.id, media.id
    accounts.delete_account(db_session, member, password=PASSWORD)
    assert db_session.get(CommunityPost, post_id).body == "Keep this content"
    assert db_session.get(CommunityMedia, media_id) and path.exists()
    decision = db_session.get(VerificationCase, case_id)
    assert decision.decided_by_user_id is None and decision.decision_note == "Reviewed"
