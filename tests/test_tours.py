"""Tour lifecycle, identity boundaries, stale requests and real role-specific pages."""

import json
import re
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

from app.models.profile import NurseProfile
from app.models.tour import UserTour
from app.models.user import User
from app.services import tours
from app.services.auth import register_user
from tests.helpers import csrf_from, register_and_sign_in


def bootstrap(response):
    assert response.status_code == 200, response.text
    match = re.search(r'<script type="application/json" id="tour-config">(.*?)</script>',
                      response.text, re.S)
    assert match, "Missing tour bootstrap"
    return json.loads(match[1])


def change(client, action, *, state=None, token=None, **values):
    if state is None:
        state = client.get("/tour").json()["state"]
    if token is None:
        token = csrf_from(client.get("/settings"))
    payload = {
        "csrf_token": token, "action": action,
        "revision": state["revision"], "run_id": state["run_id"] or "",
        **values,
    }
    return client.post("/tour", data=payload, follow_redirects=False)


def sign_out_and_in(client):
    token = csrf_from(client.get("/settings"))
    assert client.post("/auth/logout", data={"csrf_token": token}).status_code == 200
    token = csrf_from(client.get("/auth/login"))
    response = client.post("/auth/login", data={
        "csrf_token": token, "phone": "+2348012345678", "password": "s3cret-pass",
    }, follow_redirects=False)
    assert response.status_code == 303


def test_first_registration_offers_once_without_changing_welcome_flow(client, db_session):
    register_and_sign_in(client)
    welcome = bootstrap(client.get("/welcome"))
    assert welcome["offer"] is True
    assert welcome["state"]["status"] == "offered"
    user = db_session.scalar(select(User))
    assert user.onboarding_completed_at is None
    assert db_session.scalar(select(NurseProfile)) is None
    assert bootstrap(client.get("/auth/dashboard"))["offer"] is False
    sign_out_and_in(client)
    assert bootstrap(client.get("/"))["offer"] is False
    assert db_session.scalar(select(func.count()).select_from(UserTour)) == 1


def test_existing_account_gets_one_invitation_on_first_login_after_install(client, db_session):
    register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    sign_out_and_in(client)
    assert bootstrap(client.get("/"))["offer"] is True
    sign_out_and_in(client)
    assert bootstrap(client.get("/"))["offer"] is False


def test_failed_login_and_anonymous_pages_never_create_tour(client, db_session):
    register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    token = csrf_from(client.get("/auth/login"))
    response = client.post("/auth/login", data={
        "csrf_token": token, "phone": "+2348012345678", "password": "incorrect",
    })
    assert response.status_code == 401
    assert 'id="tour-config"' not in response.text
    assert db_session.scalar(select(func.count()).select_from(UserTour)) == 0


def test_prefetch_and_background_requests_do_not_consume_invitation(client):
    register_and_sign_in(client)
    assert bootstrap(client.get("/jobs", headers={"Purpose": "prefetch"}))["offer"] is False
    assert bootstrap(client.get("/jobs", headers={"Sec-Fetch-Mode": "cors"}))["offer"] is False
    assert bootstrap(client.get("/auth/dashboard"))["offer"] is True


@pytest.mark.parametrize("halfway", [False, True])
def test_skipping_invitation_or_active_tour_persists_across_login(client, db_session, halfway):
    register_and_sign_in(client)
    if halfway:
        assert change(client, "start").status_code == 200
        assert change(client, "next").status_code == 200
    assert change(client, "skip").json()["state"]["status"] == "skipped"
    row = db_session.scalar(select(UserTour))
    db_session.refresh(row)
    assert row.finished_at is not None
    sign_out_and_in(client)
    saved = bootstrap(client.get("/"))
    assert saved["offer"] is False
    assert saved["state"]["status"] == "skipped"
    assert db_session.scalar(select(User)).onboarding_completed_at is None


def test_completion_and_manual_restart_have_separate_runs(client, db_session):
    register_and_sign_in(client)
    result = change(client, "start").json()
    first_run = result["state"]["run_id"]
    for index in range(1, len(result["steps"])):
        result = change(client, "next").json()
        assert result["state"]["index"] == index
    assert change(client, "finish").json()["state"]["status"] == "completed"
    sign_out_and_in(client)
    settings = client.get("/settings")
    completed = bootstrap(settings)
    assert completed["offer"] is False
    assert completed["state"]["status"] == "completed"
    assert 'id="guided-tour-settings"' in settings.text
    assert "data-tour-start" in settings.text
    restarted = change(client, "start").json()["state"]
    assert restarted["index"] == 0
    assert restarted["run_id"] != first_run
    row = db_session.scalar(select(UserTour))
    db_session.refresh(row)
    assert row.finished_at is None
    assert row.status == "active"


def test_manual_start_for_an_existing_signed_in_account_with_no_state(client, db_session):
    register_and_sign_in(client)
    db_session.execute(delete(UserTour))
    db_session.commit()
    assert bootstrap(client.get("/settings"))["state"]["status"] == "available"
    result = change(client, "start")
    assert result.status_code == 200
    assert result.json()["state"]["index"] == 0


def test_navigation_persists_and_page_reads_do_not_advance(client):
    register_and_sign_in(client)
    state = change(client, "start").json()["state"]
    state = change(client, "next").json()["state"]
    assert state["index"] == 1
    for path in ["/jobs", "/profile/edit", "/auth/dashboard"]:
        result = bootstrap(client.get(path))
        assert result["state"] == state
        assert result["offer"] is False
    assert change(client, "previous").json()["state"]["index"] == 0
    sign_out_and_in(client)
    saved = bootstrap(client.get("/"))
    assert saved["offer"] is False
    assert saved["state"]["status"] == "active"


def test_cannot_finish_early_or_advance_past_last_step(client):
    register_and_sign_in(client)
    state = change(client, "start").json()["state"]
    assert change(client, "finish").status_code == 409
    assert change(client, "previous").status_code == 409
    assert client.get("/tour").json()["state"] == state
    for _ in range(7):
        assert change(client, "next").status_code == 200
    assert change(client, "next").status_code == 409
    assert change(client, "finish").status_code == 200
    assert change(client, "next").status_code == 409


def test_duplicate_request_and_stale_tab_cannot_jump_or_overwrite_restart(client):
    register_and_sign_in(client)
    start = change(client, "start").json()["state"]
    advanced = change(client, "next", state=start).json()["state"]
    duplicate = change(client, "next", state=start)
    assert duplicate.status_code == 409
    assert duplicate.json()["state"] == advanced
    restarted = change(client, "start").json()["state"]
    assert restarted["run_id"] != start["run_id"]
    stale = change(client, "skip", state=advanced)
    assert stale.status_code == 409
    assert stale.json()["state"] == restarted
    wrong_run = {**restarted, "run_id": start["run_id"]}
    assert change(client, "skip", state=wrong_run).status_code == 409
    assert client.get("/tour").json()["state"] == restarted


def test_missing_elements_can_be_passed_in_both_directions(client):
    register_and_sign_in(client)
    change(client, "start")
    forward = change(client, "unavailable").json()
    assert forward["state"]["index"] == 1
    assert "unavailable section" in forward["message"]
    backward = change(client, "unavailable", direction="previous").json()
    assert backward["state"]["index"] == 0
    ended = change(client, "unavailable", direction="previous").json()
    assert ended["state"]["status"] == "skipped"
    assert "no more available" in ended["message"]


def test_all_missing_targets_end_without_falsely_recording_completion(client):
    register_and_sign_in(client)
    result = change(client, "start").json()
    for _ in result["steps"]:
        result = change(client, "unavailable").json()
    assert result["state"]["status"] == "skipped"
    assert result["state"]["index"] is None


@pytest.mark.parametrize(("account_type", "staff", "extras"), [
    ("nurse", False, set()),
    ("partner", False, set()),
    ("employer", False, {"employers"}),
    ("nurse", True, {"analytics"}),
    ("employer", True, {"employers", "analytics"}),
])
def test_role_steps_point_to_real_accessible_pages_and_targets(
    client, db_session, account_type, staff, extras,
):
    register_and_sign_in(client)
    user = db_session.scalar(select(User))
    user.account_type, user.is_staff = account_type, staff
    db_session.commit()
    snapshot = client.get("/tour").json()
    standard = {"dashboard", "profile", "jobs", "people", "reels", "learning",
                "notifications", "messages"}
    assert {step["key"] for step in snapshot["steps"]} == standard | extras
    for step in snapshot["steps"]:
        page = client.get(step["path"], follow_redirects=False)
        assert page.status_code == 200, step
        assert step["target"][1:-1] in page.text, step
    assert not db_session.scalar(select(NurseProfile)), "Tour must not create/publish profiles"


def test_changed_permissions_remove_staff_and_employer_steps(client, db_session):
    register_and_sign_in(client)
    user = db_session.scalar(select(User))
    user.account_type, user.is_staff = "employer", True
    db_session.commit()
    result = change(client, "start").json()
    for _ in range(len(result["steps"]) - 1):
        change(client, "next")
    user.account_type, user.is_staff = "nurse", False
    db_session.commit()
    result = client.get("/tour").json()
    assert result["steps"][result["state"]["index"]]["key"] == "messages"
    assert not any(step["path"].startswith("/staff") for step in result["steps"])
    assert change(client, "previous").json()["state"]["index"] == 6
    assert client.get("/staff/users").status_code == 403


def test_tour_state_is_private_and_user_id_input_cannot_modify_another_user(client, db_session):
    register_and_sign_in(client)
    other = register_user(db_session, phone="+2348099999999", password="s3cret-pass")
    tours.offer_on_sign_in(db_session, other)
    tours.transition(db_session, other, action="start", revision=0, run_id=None)
    other_state = tours.snapshot(db_session, other)
    response = change(client, "skip", user_id=str(other.id), path="/staff/users", index=9)
    assert response.status_code == 200
    assert response.json()["state"]["status"] == "skipped"
    assert tours.snapshot(db_session, other) == other_state
    assert str(other.id) not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/tour").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("invalid", [
    {"action": "publish"}, {"revision": -1}, {"run_id": "bad-id"}, {"direction": "elsewhere"},
])
def test_invalid_actions_are_rejected_without_changes(client, invalid):
    register_and_sign_in(client)
    state = client.get("/tour").json()["state"]
    response = client.post("/tour", data={
        "csrf_token": csrf_from(client.get("/settings")),
        "action": "start", "revision": 0, **invalid,
    })
    assert response.status_code == 422
    assert client.get("/tour").json()["state"] == state


def test_authentication_csrf_and_revoked_sessions_are_respected(client, db_session):
    assert client.get("/tour", follow_redirects=False).status_code == 303
    register_and_sign_in(client)
    token = csrf_from(client.get("/settings"))
    assert change(client, "start", token="wrong").status_code == 400
    user = db_session.scalar(select(User))
    user.auth_version += 1
    db_session.commit()
    response = client.post("/tour", data={
        "action": "start", "revision": 0, "csrf_token": token,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert db_session.scalar(select(UserTour)).status == "offered"


def test_deleting_account_cascades_private_tour_progress(client, db_session):
    register_and_sign_in(client)
    change(client, "start")
    db_session.execute(delete(User))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(UserTour)) == 0


def test_tour_invitation_failure_does_not_block_authentication(client, db_session, monkeypatch):
    def unavailable(*args):
        raise OperationalError("test", {}, Exception("temporary failure"))

    monkeypatch.setattr(tours, "_insert_offer", unavailable)
    register_and_sign_in(client)
    response = client.get("/")
    assert response.status_code == 200
    assert bootstrap(response)["state"]["status"] == "available"
    assert db_session.scalar(select(User)) is not None


def test_no_new_offer_on_repeat_sign_in_or_version_change(db_session, monkeypatch):
    user = register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    assert tours.offer_on_sign_in(db_session, user) is True
    assert tours.offer_on_sign_in(db_session, user) is False
    state = tours.transition(db_session, user, action="start", revision=0, run_id=None)["state"]
    tours.transition(
        db_session, user, action="skip", revision=state["revision"], run_id=UUID(state["run_id"]),
    )
    monkeypatch.setattr(tours, "TOUR_VERSION", 2)
    assert tours.offer_on_sign_in(db_session, user) is False
    assert tours.snapshot(db_session, user)["state"]["status"] == "skipped"
