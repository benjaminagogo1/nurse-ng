"""Media boundary regressions: grants, raw signed events and private storage.

These tests use synthetic credentials and mocked RPC transport. They neither
open an external meeting nor claim that live-provider deployment is configured.
Domain authorization and webhook transaction receipts are tested separately.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.services import education_live as live


@pytest.fixture
def provider(monkeypatch):
    values = SimpleNamespace(
        livekit_url="wss://classrooms.example.com",
        livekit_api_key="synthetic-provider-key",
        livekit_api_secret="synthetic-provider-secret" * 2,
        livekit_token_seconds=300,
        learning_recording_s3_bucket="private-learning-recordings",
        learning_recording_s3_region="eu-west-1",
        learning_recording_s3_endpoint="https://storage.example.com",
        learning_recording_s3_access_key="synthetic-storage-access",
        learning_recording_s3_secret_key="synthetic-storage-secret",
        learning_recording_s3_force_path_style=True,
    )
    monkeypatch.setattr(live, "settings", values)
    return values


def decode(token, provider):
    return jwt.decode(
        token,
        provider.livekit_api_secret,
        algorithms=["HS256"],
        issuer=provider.livekit_api_key,
    )


def signed_event(body, provider, **overrides):
    claims = {
        "iss": provider.livekit_api_key,
        "exp": datetime.now(UTC) + timedelta(minutes=2),
        "sha256": base64.b64encode(hashlib.sha256(body).digest()).decode(),
        **overrides,
    }
    return jwt.encode(claims, provider.livekit_api_secret, algorithm="HS256")


def test_lecture_learner_grant_cannot_publish_admin_or_data_and_hides_private_name(provider):
    user = SimpleNamespace(id=uuid4(), community_name="", full_name="Private account name")
    session = uuid4()
    result = live.participant_token(session, user)
    claims = decode(result["token"], provider)
    assert claims["sub"] == str(user.id)
    assert claims["name"] == "Learner"
    assert claims["video"]["room"] == live.room_name(session)
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["canPublish"] is False
    assert claims["video"]["canPublishData"] is False
    assert claims["video"]["roomAdmin"] is False
    assert claims["exp"] - claims["iat"] == 300


def test_host_and_discussion_grants_keep_administration_on_server(provider):
    user = SimpleNamespace(id=uuid4(), community_name="Nurse Ada")
    session = uuid4()
    host = decode(
        live.participant_token(session, user, is_host=True, display_name="Educator Ada")["token"],
        provider,
    )
    learner = decode(
        live.participant_token(session, user, can_speak=True, session_format="discussion")["token"],
        provider,
    )
    assert host["name"] == "Educator Ada"
    assert host["video"]["canPublishSources"] == [
        "camera",
        "microphone",
        "screen_share",
        "screen_share_audio",
    ]
    assert learner["video"]["canPublishSources"] == ["camera", "microphone"]
    assert host["video"]["roomAdmin"] is learner["video"]["roomAdmin"] is False


def test_revoked_discussion_speaking_does_not_return_with_a_fresh_token(provider):
    user = SimpleNamespace(id=uuid4(), community_name="Learner")
    grant = live.participant_token(uuid4(), user, session_format="discussion", can_speak=False)
    assert decode(grant["token"], provider)["video"]["canPublish"] is False


def test_invalid_namespace_and_unconfigured_provider_fail_closed(provider):
    with pytest.raises(live.EducationLiveError, match="identifier"):
        live.room_name("another-customer-room")
    provider.livekit_api_secret = ""
    assert live.provider_status() == {"configured": False, "recording_configured": False}
    with pytest.raises(live.EducationLiveError, match="activation"):
        live.participant_token(uuid4(), SimpleNamespace(id=uuid4(), community_name="Learner"))


def test_webhook_checks_exact_body_algorithm_issuer_and_expiry(provider):
    event = {
        "id": "EV_fixture",
        "event": "participant_joined",
        "room": {"name": live.room_name(uuid4())},
    }
    body = json.dumps(event, ensure_ascii=False).encode()
    token = signed_event(body, provider)
    assert live.verify_webhook(body, "Bearer " + token) == event
    with pytest.raises(live.EducationLiveError, match="signature"):
        live.verify_webhook(body + b" ", token)
    with pytest.raises(live.EducationLiveError, match="signature"):
        live.verify_webhook(body, signed_event(body, provider, iss="other-provider"))
    with pytest.raises(live.EducationLiveError, match="signature"):
        live.verify_webhook(
            body, signed_event(body, provider, exp=datetime.now(UTC) - timedelta(minutes=1))
        )
    invalid = jwt.encode(
        {"iss": provider.livekit_api_key, "exp": datetime.now(UTC) + timedelta(minutes=1)},
        provider.livekit_api_secret,
        algorithm="HS384",
    )
    with pytest.raises(live.EducationLiveError, match="signature"):
        live.verify_webhook(body, invalid)


def test_normalization_excludes_other_rooms_keys_public_urls_and_storage_secrets(provider):
    session = uuid4()
    key = f"learning/{session}/lecture.mp4"
    raw = {
        "id": "EV_recording",
        "event": "egress_ended",
        "createdAt": 1780000000,
        "egressInfo": {
            "egressId": "EG_recording",
            "roomName": live.room_name(session),
            "status": 3,
            "roomComposite": {"fileOutputs": [{"s3": {"secret": "should-not-persist"}}]},
            "fileResults": [
                {
                    "filename": key,
                    "location": "https://public.example.com/private.mp4",
                    "size": "600",
                },
                {"filename": f"learning/{uuid4()}/other.mp4"},
            ],
        },
    }
    result = live.normalize_provider_event(raw)
    egress = result["payload"]["egressInfo"]
    assert egress["fileResults"] == [{"filename": key, "size": "600", "duration": 0}]
    assert "roomComposite" not in egress
    assert "public.example" not in json.dumps(result["payload"])
    assert "should-not-persist" not in json.dumps(result["payload"])
    assert (
        live.normalize_provider_event({**raw, "egressInfo": {"roomName": "other-tenant"}}) is None
    )


def test_normalization_canonicalizes_protobuf_egress_field_names_and_enum(provider):
    session = uuid4()
    result = live.normalize_provider_event(
        {
            "id": "EV_proto_recording",
            "event": "egress_ended",
            "created_at": 1780000000,
            "egress_info": {
                "egress_id": "EG_proto_recording",
                "room_name": live.room_name(session),
                "status": "EGRESS_COMPLETE",
                "file_results": [{"filename": f"learning/{session}/lecture.mp4"}],
            },
        }
    )
    assert result["payload"]["egressInfo"]["egressId"] == "EG_proto_recording"
    assert result["payload"]["egressInfo"]["status"] == 3
    assert "egress_id" not in result["payload"]["egressInfo"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("room", ["invalid"]),
        ("participant", "invalid"),
        ("egressInfo", ["invalid"]),
    ],
)
def test_malformed_provider_objects_have_a_safe_error(provider, field, value):
    with pytest.raises(live.EducationLiveError, match="metadata"):
        live.normalize_provider_event(
            {
                "id": "EV_malformed",
                "event": "participant_joined",
                "room": {"name": live.room_name(uuid4())},
                field: value,
            }
        )


@pytest.mark.parametrize("kind", [["participant_joined"], {"event": "participant_joined"}, None])
def test_malformed_provider_event_kind_has_a_safe_error(provider, kind):
    with pytest.raises(live.EducationLiveError, match="metadata"):
        live.normalize_provider_event({"id": "EV_invalid_kind", "event": kind})


@pytest.mark.parametrize("files", ["invalid", {"filename": "invalid"}, [None]])
def test_malformed_recording_file_results_have_a_safe_error(provider, files):
    with pytest.raises(live.EducationLiveError, match="metadata"):
        live.normalize_provider_event(
            {
                "id": "EV_malformed_files",
                "event": "egress_ended",
                "egressInfo": {
                    "roomName": live.room_name(uuid4()),
                    "egressId": "EG_malformed",
                    "fileResults": files,
                },
            }
        )


def test_private_recording_get_is_expiring_session_scoped_and_not_a_bucket_grant(provider):
    session = uuid4()
    key = f"learning/{session}/class.mp4"
    url = live.recording_download_url(
        key, session_id=session, now=datetime(2026, 11, 20, tzinfo=UTC)
    )
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "storage.example.com"
    assert parsed.path == "/private-learning-recordings/" + key
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert "synthetic-storage-secret" not in url
    with pytest.raises(live.EducationLiveError, match="another classroom"):
        live.recording_download_url(key, session_id=uuid4())
    for invalid in (
        "https://public.example/video.mp4",
        "../private.mp4",
        f"learning/{session}/../video.mp4",
    ):
        with pytest.raises(live.EducationLiveError):
            live.recording_download_url(invalid)


def test_start_recording_uses_private_storage_and_waits_for_trusted_completion(
    provider, monkeypatch
):
    captured = {}

    def rpc(service, method, payload, grants):
        captured.update(service=service, method=method, payload=payload, grants=grants)
        return {"egressId": "EG_recording"}

    monkeypatch.setattr(live, "_call", rpc)
    session = uuid4()
    result = live.start_recording(session)
    assert result["status"] == "starting"
    assert result["object_key"].startswith(f"learning/{session}/")
    assert captured["grants"]["roomRecord"] is True
    assert (
        captured["payload"]["fileOutputs"][0]["s3"]["bucket"]
        == provider.learning_recording_s3_bucket
    )
    assert "acl" not in captured["payload"]["fileOutputs"][0]["s3"]


def test_server_moderation_only_changes_target_and_never_forces_microphone_on(
    provider, monkeypatch
):
    calls = []
    monkeypatch.setattr(live, "_call", lambda *args: calls.append(args) or {})
    session, learner = uuid4(), uuid4()
    live.moderate_participant(session, learner, action="allow_speaking")
    assert calls[-1][1] == "UpdateParticipant"
    assert calls[-1][2]["permission"]["canPublishData"] is False
    assert calls[-1][2]["permission"]["canPublishSources"] == [1, 2]
    assert calls[-1][3] == {"room": live.room_name(session), "roomAdmin": True}
    live.delete_room(session)
    assert calls[-1][1] == "DeleteRoom"
    assert calls[-1][3]["roomCreate"] is True
    with pytest.raises(live.EducationLiveError):
        live.moderate_participant(session, learner, action="unmute")


@pytest.mark.parametrize("status", [404, 503])
def test_room_closure_retries_accept_only_an_already_absent_room(provider, monkeypatch, status):
    def failed_request(*args, **kwargs):
        raise HTTPError("https://classrooms.example.com", status, "Provider failure", None, None)

    monkeypatch.setattr(live, "build_opener", lambda *args: SimpleNamespace(open=failed_request))
    if status == 404:
        assert live.delete_room(uuid4()) == {}
    else:
        with pytest.raises(live.EducationLiveError, match="could not complete"):
            live.delete_room(uuid4())


def test_settings_reject_partial_live_credentials_and_unsafe_production_origin():
    base = {"_env_file": None, "environment": "development", "secret_key": "x" * 40}
    with pytest.raises(ValueError, match="requires"):
        Settings(**base, livekit_url="wss://classrooms.example.com")
    configured = Settings(
        **base,
        livekit_url="wss://classrooms.example.com",
        livekit_api_key="fixture",
        livekit_api_secret="s" * 40,
    )
    assert configured.livekit_url == "wss://classrooms.example.com"
    with pytest.raises(ValueError, match="WebSocket origin"):
        Settings(
            **base,
            livekit_url="wss://user:password@classrooms.example.com",
            livekit_api_key="fixture",
            livekit_api_secret="s" * 40,
        )
