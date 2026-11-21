"""Managed classroom media, signed attendance events and private recordings.

This module is a transport boundary, not a learner authorization boundary.
Routes MUST first ask ``education.join_session``/host authorization whether an
active account may act on a particular session. They then pass that session's
UUID here. Room names are deterministic and namespaced; callers cannot select a
different LiveKit room. Browser grants contain only room-join/subscription and
explicit publishing permissions. Host administration and recording grants are
used only in server-to-server RPCs, never returned to a browser.

LiveKit's webhook JWT signs a SHA-256 digest of the *exact request bytes*.
Re-serializing JSON before verification breaks that binding. ``verify_webhook``
checks issuer, algorithm, expiry and constant-time digest equality; the domain
service then records the event ID in its transactional replay receipt. Neither
browser pings nor chat messages establish attendance or completed recordings.

Recordings are written by LiveKit egress into an operator-controlled private
S3-compatible bucket. Completed signed provider events retain an object key.
After rechecking learner access, a route may issue a short-lived signed GET URL.
This module never changes bucket ACLs or accepts user-selected storage origins.
Provider failures are sanitized so bearer grants, API secrets and S3 credentials
cannot reach feedback, logs or rendered error pages.
"""

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

import jwt

from app.core.config import settings

ROOM_PREFIX = "nurse-learning-"
MAX_PROVIDER_BYTES = 1024 * 1024
SUPPORTED_EVENTS = frozenset(
    {
        "participant_joined",
        "participant_left",
        "room_started",
        "room_finished",
        "egress_started",
        "egress_updated",
        "egress_ended",
    }
)


class EducationLiveError(ValueError):
    """A safe, user-displayable live-service failure with no provider secrets."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward a server grant to a different origin.
        return None


def provider_status():
    """Report capability presence only; this does not claim a successful call."""
    configured = bool(
        settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret
    )
    return {
        "configured": configured,
        "recording_configured": configured
        and bool(
            settings.learning_recording_s3_bucket
            and settings.learning_recording_s3_access_key
            and settings.learning_recording_s3_secret_key
        ),
    }


def room_name(session_id):
    """Derive the single tenant room allowed for a persisted learning-session UUID."""
    try:
        return ROOM_PREFIX + str(UUID(str(session_id)))
    except (ValueError, TypeError, AttributeError):
        raise EducationLiveError("This classroom identifier is invalid.") from None


def _identity(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise EducationLiveError("This participant identifier is invalid.") from None


def _require_provider(*, recording=False):
    capabilities = provider_status()
    if not capabilities["configured"]:
        raise EducationLiveError(
            "Live classrooms are awaiting video-service activation. Please contact the organiser."
        )
    if recording and not capabilities["recording_configured"]:
        raise EducationLiveError(
            "Private recording storage has not been configured for this classroom."
        )


def _grant(video, *, identity=None, name=None, ttl=None):
    _require_provider()
    now = datetime.now(UTC)
    claims = {
        "iss": settings.livekit_api_key,
        "iat": now,
        "nbf": now - timedelta(seconds=5),
        "exp": now + timedelta(seconds=ttl or settings.livekit_token_seconds),
        "video": video,
    }
    if identity:
        claims["sub"] = _identity(identity)
    if name:
        claims["name"] = str(name).strip()[:80]
    return jwt.encode(claims, settings.livekit_api_secret, algorithm="HS256")


def _call(service, method, payload, grants):
    """Bounded TLS RPC to the configured origin; never follows redirects.

    ``service`` and ``method`` come from module constants below, not request
    input. The private grant expires quickly even if the provider is unavailable.
    HTTP/JSON failures have one sanitized error contract for callers.
    """
    _require_provider()
    origin = urlsplit(settings.livekit_url)
    scheme = "https" if origin.scheme == "wss" else "http"
    path = f"/twirp/livekit.{service}/{method}"
    endpoint = urlunsplit((scheme, origin.netloc, path, "", ""))
    request = Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + _grant(grants, ttl=120),
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(MAX_PROVIDER_BYTES + 1)
        if len(raw) > MAX_PROVIDER_BYTES:
            raise EducationLiveError("The video service returned an oversized response.")
        parsed = json.loads(raw or b"{}")
        if not isinstance(parsed, dict):
            raise ValueError
        return parsed
    except HTTPError as exc:
        if exc.code == 404:
            raise EducationLiveError(
                "The classroom or participant is no longer connected."
            ) from None
        raise EducationLiveError(
            "The video service could not complete this action. Please retry shortly."
        ) from None
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        raise EducationLiveError(
            "The video service is temporarily unavailable. Please retry shortly."
        ) from None


def create_room(session_id, *, max_participants=100, metadata=""):
    """Create/reuse the session room after an approved host starts the session.

    The domain must serialize concurrent start requests. Metadata is internal
    context only and must not include private account/contact information.
    """
    name = room_name(session_id)
    if not isinstance(max_participants, int) or not 1 <= max_participants <= 1000:
        raise EducationLiveError("Choose a classroom capacity between 1 and 1,000.")
    return _call(
        "RoomService",
        "CreateRoom",
        {
            "name": name,
            "emptyTimeout": 600,
            "departureTimeout": 120,
            "maxParticipants": max_participants,
            "metadata": str(metadata)[:1000],
        },
        {"roomCreate": True},
    )


def delete_room(session_id):
    """End the remote room and disconnect its participants before domain closure."""
    name = room_name(session_id)
    try:
        return _call(
            "RoomService", "DeleteRoom", {"room": name}, {"room": name, "roomCreate": True}
        )
    except EducationLiveError as exc:
        if str(exc) == "The classroom or participant is no longer connected.":
            return {}  # Ending an already removed room is idempotent.
        raise


def participant_token(
    session_id,
    user,
    *,
    is_host=False,
    can_speak=False,
    session_format="lecture",
    display_name=None,
):
    """Issue a room-scoped browser grant after authoritative domain checks.

    Lecture learners subscribe and listen until the host grants speaking.
    Discussion registrations normally grant speaking in the domain; the stored
    ``can_speak`` value remains authoritative after a host revokes that right.
    Screen sharing is reserved to hosts. The SDK data channel is disabled because app-mediated
    questions/chat have their own authorization, moderation and persistence.
    A private ``full_name`` is deliberately never used as the participant name.
    """
    name = room_name(session_id)
    identity = _identity(user.id)
    if session_format not in {"lecture", "discussion"}:
        raise EducationLiveError("This classroom format is invalid.")
    publish = bool(is_host or can_speak)
    sources = ["camera", "microphone"] if publish else []
    if is_host:
        sources += ["screen_share", "screen_share_audio"]
    grants = {
        "room": name,
        "roomJoin": True,
        "canSubscribe": True,
        "canPublish": publish,
        "canPublishData": False,
        "canPublishSources": sources,
        "roomAdmin": False,
    }
    visible_name = display_name or getattr(user, "community_name", "") or "Learner"
    return {
        "url": settings.livekit_url,
        "token": _grant(grants, identity=identity, name=visible_name),
        "identity": identity,
        "room": name,
        "is_host": bool(is_host),
        "can_publish": publish,
        "expires_in": settings.livekit_token_seconds,
    }


def list_participants(session_id):
    """Return provider participant state for an already-authorized classroom."""
    name = room_name(session_id)
    response = _call(
        "RoomService", "ListParticipants", {"room": name}, {"room": name, "roomAdmin": True}
    )
    rows = response.get("participants", [])
    return rows if isinstance(rows, list) else []


def moderate_participant(session_id, identity, *, action):
    """Apply host moderation after routes validate owner and target registration.

    Mute never forces a microphone on. Speaking permission changes allow the
    learner to choose whether to publish. Removal requires the domain to retain
    exclusion state so a removed learner cannot obtain a fresh join grant.
    """
    name, identity = room_name(session_id), _identity(identity)
    grants = {"room": name, "roomAdmin": True}
    if action == "remove":
        return _call(
            "RoomService", "RemoveParticipant", {"room": name, "identity": identity}, grants
        )
    if action in {"allow_speaking", "revoke_speaking"}:
        allowed = action == "allow_speaking"
        return _call(
            "RoomService",
            "UpdateParticipant",
            {
                "room": name,
                "identity": identity,
                "permission": {
                    "canSubscribe": True,
                    "canPublish": allowed,
                    "canPublishData": False,
                    "canPublishSources": [1, 2] if allowed else [],
                },
            },
            grants,
        )
    if action == "mute":
        participant = next(
            (row for row in list_participants(session_id) if row.get("identity") == identity), None
        )
        if participant is None:
            raise EducationLiveError("This participant is no longer connected.")
        count = 0
        for track in participant.get("tracks", []):
            if track.get("source") in {2, 4, "MICROPHONE", "SCREEN_SHARE_AUDIO"}:
                _call(
                    "RoomService",
                    "MutePublishedTrack",
                    {
                        "room": name,
                        "identity": identity,
                        "trackSid": track.get("sid"),
                        "muted": True,
                    },
                    grants,
                )
                count += 1
        return {"muted_tracks": count}
    raise EducationLiveError("Choose a supported classroom moderation action.")


def verify_webhook(raw_body, authorization):
    """Verify raw bytes before parsing; return the authenticated provider event.

    Routes must pass the untouched request body and its Authorization header.
    Event replay and state transitions belong to the transactional domain hook.
    """
    _require_provider()
    if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > MAX_PROVIDER_BYTES:
        raise EducationLiveError("The classroom event body is invalid.")
    token = str(authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        claims = jwt.decode(
            token,
            settings.livekit_api_secret,
            algorithms=["HS256"],
            issuer=settings.livekit_api_key,
            leeway=15,
            options={"require": ["iss", "exp", "sha256"]},
        )
        digest = base64.b64encode(hashlib.sha256(raw_body).digest()).decode()
        provided = claims.get("sha256")
        if not isinstance(provided, str) or not hmac.compare_digest(provided, digest):
            raise ValueError
        event = json.loads(raw_body)
        if not isinstance(event, dict):
            raise ValueError
    except (jwt.PyJWTError, ValueError, UnicodeError):
        raise EducationLiveError("The classroom event signature is invalid.") from None
    if not isinstance(event.get("id"), str) or not 1 <= len(event["id"]) <= 128:
        raise EducationLiveError("The classroom event identifier is invalid.")
    return event


def normalize_provider_event(event):
    """Extract an event envelope for ``education.apply_provider_event``.

    Unknown project rooms/events return ``None`` and may be acknowledged without
    changing education state. Recording filenames are validated against the
    room/session prefix rather than trusting a provider URL as private storage.
    """
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        raise EducationLiveError("The classroom event metadata is invalid.")
    kind = event.get("event")
    if kind not in SUPPORTED_EVENTS:
        return None
    egress = event.get("egressInfo") or event.get("egress_info") or {}
    room = event.get("room") or {}
    participant = event.get("participant") or {}
    if any(not isinstance(value, dict) for value in (egress, room, participant)):
        raise EducationLiveError("The classroom event metadata is invalid.")
    name = room.get("name") or egress.get("roomName") or egress.get("room_name")
    if not isinstance(name, str) or not name.startswith(ROOM_PREFIX):
        return None
    try:
        session_id = UUID(name[len(ROOM_PREFIX) :])
        if name != room_name(session_id):
            return None
        stamp = float(event.get("createdAt") or event.get("created_at") or 0)
        occurred_at = datetime.fromtimestamp(stamp, UTC) if stamp > 0 else datetime.now(UTC)
    except (ValueError, OverflowError, OSError, TypeError):
        raise EducationLiveError("The classroom event metadata is invalid.") from None
    payload = {
        "id": event["id"],
        "event": kind,
        "createdAt": int(occurred_at.timestamp()),
        "room": {"name": name},
        "participant": {key: participant[key] for key in ("identity", "sid") if key in participant},
    }
    if egress:
        # Protobuf JSON accepts both snake_case and lowerCamelCase field names.
        # Give the domain one stable vocabulary, regardless of provider encoding.
        field_names = {
            "egressId": "egress_id",
            "roomName": "room_name",
            "status": "status",
            "startedAt": "started_at",
            "endedAt": "ended_at",
        }
        safe_egress = {}
        for canonical, alternate in field_names.items():
            if canonical in egress:
                safe_egress[canonical] = egress[canonical]
            elif alternate in egress:
                safe_egress[canonical] = egress[alternate]
        status = safe_egress.get("status")
        if isinstance(status, str):
            enum_states = {
                "EGRESS_STARTING": 0,
                "EGRESS_ACTIVE": 1,
                "EGRESS_ENDING": 2,
                "EGRESS_COMPLETE": 3,
                "EGRESS_FAILED": 4,
                "EGRESS_ABORTED": 5,
                "EGRESS_LIMIT_REACHED": 6,
            }
            safe_egress["status"] = enum_states.get(status, status)
        files = egress.get("fileResults") or egress.get("file_results") or []
        if not isinstance(files, list) or any(not isinstance(file, dict) for file in files):
            raise EducationLiveError("The classroom event metadata is invalid.")
        valid_files = []
        for file in files:
            try:
                key = _recording_key(file.get("filename", ""), session_id=session_id)
            except EducationLiveError:
                continue
            valid_files.append(
                {"filename": key, "size": file.get("size", 0), "duration": file.get("duration", 0)}
            )
        safe_egress["fileResults"] = valid_files
        # Retain only the identifiers, state and private object keys above.
        # Egress request fields may contain storage credentials and public URLs.
        payload["egressInfo"] = safe_egress
    return {
        "event_id": event["id"],
        "event_type": kind,
        "room_name": name,
        "payload": payload,
        "occurred_at": occurred_at,
    }


def start_recording(session_id):
    """Start server egress only after host authorization and recording consent.

    Egress acceptance means 'starting', not a playable recording. A verified
    complete event with the exact private object key establishes playback state.
    """
    _require_provider(recording=True)
    name = room_name(session_id)
    filename = f"learning/{UUID(str(session_id))}/{uuid4()}.mp4"
    s3 = {
        "accessKey": settings.learning_recording_s3_access_key,
        "secret": settings.learning_recording_s3_secret_key,
        "region": settings.learning_recording_s3_region,
        "bucket": settings.learning_recording_s3_bucket,
        "forcePathStyle": settings.learning_recording_s3_force_path_style,
    }
    if settings.learning_recording_s3_endpoint:
        s3["endpoint"] = settings.learning_recording_s3_endpoint
    result = _call(
        "Egress",
        "StartRoomCompositeEgress",
        {
            "roomName": name,
            "layout": "speaker",
            "audioOnly": False,
            "fileOutputs": [
                {"fileType": 1, "filepath": filename, "disableManifest": True, "s3": s3}
            ],
        },
        {"roomRecord": True, "room": name},
    )
    egress_id = result.get("egressId") or result.get("egress_id")
    if not isinstance(egress_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", egress_id):
        raise EducationLiveError("The video service did not confirm a recording identifier.")
    return {"egress_id": egress_id, "object_key": filename, "status": "starting"}


def stop_recording(egress_id):
    """Stop an egress ID already loaded from this session's authorized records."""
    if not isinstance(egress_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", egress_id):
        raise EducationLiveError("This recording identifier is invalid.")
    return _call("Egress", "StopEgress", {"egressId": egress_id}, {"roomRecord": True})


def _recording_key(value, *, session_id=None):
    if not isinstance(value, str) or not re.fullmatch(
        r"learning/[0-9a-f-]{36}/[A-Za-z0-9_.-]{1,160}\.mp4",
        value,
    ):
        raise EducationLiveError("This private recording location is invalid.")
    parts = value.split("/")
    identity = _identity(parts[1])
    if identity != parts[1] or ".." in parts[2]:
        raise EducationLiveError("This private recording location is invalid.")
    if session_id is not None and identity != _identity(session_id):
        raise EducationLiveError("This recording belongs to another classroom.")
    return value


def recording_download_url(key, *, session_id=None, now=None):
    """Sign a five-minute private S3 GET after learner/session authorization.

    Supports AWS S3 and HTTPS S3-compatible origins with AWS Signature Version 4.
    No bucket listing, upload or delete grant is returned. Keys are restricted to
    this module's recording namespace; callers should pass ``session_id`` too.
    """
    _require_provider(recording=True)
    key = _recording_key(key, session_id=session_id)
    now = now or datetime.now(UTC)
    now = now.astimezone(UTC)
    region = settings.learning_recording_s3_region
    endpoint = settings.learning_recording_s3_endpoint or f"https://s3.{region}.amazonaws.com"
    origin = urlsplit(endpoint)
    bucket = settings.learning_recording_s3_bucket
    if settings.learning_recording_s3_force_path_style:
        host, path = origin.netloc, "/" + bucket + "/" + key
    else:
        host, path = bucket + "." + origin.netloc, "/" + key
    path = quote(path, safe="/-_.~")
    day, stamp = now.strftime("%Y%m%d"), now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{day}/{region}/s3/aws4_request"
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": settings.learning_recording_s3_access_key + "/" + scope,
        "X-Amz-Date": stamp,
        "X-Amz-Expires": "300",
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = urlencode(sorted(query.items()), quote_via=quote, safe="-_.~")
    canonical = f"GET\n{path}\n{canonical_query}\nhost:{host}\n\nhost\nUNSIGNED-PAYLOAD"
    to_sign = (
        f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    )

    def sign(secret, value):
        return hmac.new(secret, value.encode(), hashlib.sha256).digest()

    signing = ("AWS4" + settings.learning_recording_s3_secret_key).encode()
    for value in (day, region, "s3", "aws4_request"):
        signing = sign(signing, value)
    signature = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
    return urlunsplit(
        (origin.scheme, host, path, canonical_query + "&X-Amz-Signature=" + signature, "")
    )
