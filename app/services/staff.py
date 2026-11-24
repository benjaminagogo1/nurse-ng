"""Existing administrators can grant or revoke another account's administrator role.

Only a current administrator may change another account's administrator flag.
Role events record actor and outcome; ordinary account types and educator or
employer approval remain independent permission domains.
"""

from sqlalchemy import exists, select, update
from sqlalchemy.orm import aliased

from app.models.staff import StaffRoleEvent
from app.models.user import User, UserStatus
from app.services.accounts import verify_current_password
from app.services.auth import AuthError


def change_admin(db, actor, target, *, enabled, current_password, expected_version):
    if not actor.is_staff or not actor.is_active or actor.status != UserStatus.ACTIVE:
        raise AuthError("Administrator access is required.")
    if actor.id == target.id:
        raise AuthError("You cannot change your own administrator access.")
    verify_current_password(db, actor, current_password)
    if not actor.is_staff:
        raise AuthError("Your administrator access has changed. Reload this page.")
    if enabled and (not target.is_active or target.status != UserStatus.ACTIVE):
        raise AuthError("Only active accounts can become administrators.")
    # Serialize role decisions on PostgreSQL, including two admins attempting to
    # revoke one another. SQLite serializes writers; the write predicate below
    # still rechecks the actor after a competing decision has committed.
    list(db.scalars(select(User.id).where(User.is_staff.is_(True))
                    .order_by(User.id).with_for_update()))
    reviewer = aliased(User)
    permitted = exists(select(reviewer.id).where(
        reviewer.id == actor.id, reviewer.is_staff.is_(True),
        reviewer.is_active.is_(True), reviewer.status == UserStatus.ACTIVE,
        reviewer.auth_version == actor.auth_version,
    ))
    conditions = [User.id == target.id, User.auth_version == expected_version,
                  User.is_staff.is_(not enabled), permitted]
    if enabled:
        conditions.extend([User.is_active.is_(True), User.status == UserStatus.ACTIVE])
    changed = db.execute(update(User).where(*conditions).values(
        is_staff=enabled, auth_version=User.auth_version + 1,
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise AuthError("This account's access changed. Reload the page before trying again.")
    db.add(StaffRoleEvent(actor_id=actor.id, target_id=target.id,
                         action="granted" if enabled else "revoked"))
    db.commit()
    db.expire(target)
