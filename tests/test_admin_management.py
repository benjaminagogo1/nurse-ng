"""Only current administrators can change someone else's role, with an audit trail."""

import pytest
from sqlalchemy import func, select

from app.models.staff import StaffRoleEvent
from app.services.auth import register_user
from tests.helpers import csrf_from
from tests.test_community import PASSWORD, sign_in


@pytest.fixture
def people(db_session):
    admin = register_user(db_session, phone="+2348000082001", password=PASSWORD,
                          full_name="Existing Administrator")
    target = register_user(db_session, phone="+2348000082002", password=PASSWORD,
                           full_name="Trusted Member", email="trusted@example.org")
    admin.is_staff = True
    db_session.commit()
    return admin, target


def change(client, target, *, action="grant", password=PASSWORD, version=None):
    token = csrf_from(client.get("/staff/admins"))
    return client.post(f"/staff/admins/{target.id}", data={
        "csrf_token": token, "action": action, "current_password": password,
        "expected_version": target.auth_version if version is None else version,
    }, follow_redirects=False)


def test_admin_search_grant_revoke_and_old_sessions_are_invalidated(client, db_session, people):
    admin, target = people
    sign_in(client, target.phone)
    old_session = dict(client.cookies)
    sign_in(client, admin.phone)
    page = client.get("/staff/admins?q=trusted@example.org")
    assert page.status_code == 200 and "Trusted Member" in page.text
    assert "Make administrator" in page.text and "no-store" in page.headers["cache-control"]
    assert change(client, target).status_code == 303
    db_session.refresh(target)
    assert target.is_staff and target.auth_version == 1
    assert change(client, target, version=0).status_code == 400
    assert db_session.scalar(select(func.count()).select_from(StaffRoleEvent)) == 1
    client.cookies.clear()
    client.cookies.update(old_session)
    assert client.get("/staff/admins", follow_redirects=False).status_code == 303
    sign_in(client, target.phone)
    assert client.get("/staff/admins").status_code == 200
    promoted_session = dict(client.cookies)
    sign_in(client, admin.phone)
    assert change(client, target, action="revoke").status_code == 303
    db_session.refresh(target)
    assert not target.is_staff and target.auth_version == 2
    events = list(db_session.scalars(select(StaffRoleEvent).order_by(StaffRoleEvent.id)))
    assert [event.action for event in events] == ["granted", "revoked"]
    assert all(event.actor_id == admin.id and event.target_id == target.id for event in events)
    client.cookies.clear()
    client.cookies.update(promoted_session)
    assert client.get("/staff/admins", follow_redirects=False).status_code == 303


def test_admin_tools_require_authentication_authority_csrf_and_current_password(
    client, db_session, people,
):
    admin, target = people
    assert client.get("/staff/admins", follow_redirects=False).status_code == 303
    sign_in(client, target.phone)
    assert client.get("/staff/admins").status_code == 403
    assert client.post(f"/staff/admins/{admin.id}", data={}).status_code == 403
    sign_in(client, admin.phone)
    assert client.post(f"/staff/admins/{target.id}", data={}).status_code == 400
    for password in ("", "wrong-password"):
        response = change(client, target, password=password)
        assert response.status_code == 400
        assert 'value="wrong-password"' not in response.text
    db_session.refresh(target)
    assert not target.is_staff
    assert db_session.scalar(select(func.count()).select_from(StaffRoleEvent)) == 0


def test_self_removal_and_inactive_account_promotion_are_rejected(client, db_session, people):
    admin, target = people
    sign_in(client, admin.phone)
    assert change(client, admin, action="revoke").status_code == 400
    db_session.refresh(admin)
    assert admin.is_staff
    target.status = "suspended"
    db_session.commit()
    assert change(client, target).status_code == 400
    assert not target.is_staff
