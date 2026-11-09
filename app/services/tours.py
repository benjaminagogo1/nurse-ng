"""Role-aware tour definitions and atomic progress transitions.

Only this registry supplies destinations and target selectors. The browser sends
actions, never user IDs, arbitrary destinations, or a claimed completion step.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.tour import UserTour
from app.models.user import User, UserStatus

logger = logging.getLogger(__name__)
TOUR_VERSION = 1


@dataclass(frozen=True)
class TourStep:
    key: str
    path: str
    title: str
    body: str
    role: str = "all"
    aliases: tuple[str, ...] = ()

    def available_to(self, user: User) -> bool:
        return (
            self.role == "all"
            or (self.role == "staff" and user.is_staff)
            or self.role == user.account_type
        )

    def public(self) -> dict:
        values = asdict(self)
        values.pop("role")
        values["target"] = f'[data-tour="{self.key}"]'
        return values


# Keep stable keys when changing copy or moving pages. Bumping the version does
# not re-offer a dismissed tour; a manual restart picks up the current registry.
STEPS = (
    TourStep(
        "dashboard", "/auth/dashboard", "Your day, at a glance",
        "Your dashboard brings together job opportunities, messages and network "
        "connections. Use these shortcuts to pick up where you left off.",
        aliases=("/",),
    ),
    TourStep(
        "profile", "/profile/edit", "Tell your professional story",
        "Add your experience, skills and interests here. New profiles start private. "
        "Use your profile’s sharing controls to choose what other people can see.",
    ),
    TourStep(
        "jobs", "/jobs", "Find your next opportunity",
        "Search nursing roles and filter by location, including Nigerian and international "
        "opportunities. Open a listing for its details, application route and closing date.",
    ),
    TourStep(
        "people", "/nurses", "Meet your professional community",
        "Find people by their published name, skills or location. Only shared profile "
        "details appear here. Open a profile to connect, then manage requests in Network.",
    ),
    TourStep(
        "reels", "/reels", "A fresh perspective, in a short video",
        "Explore professional Reels and share a video of your own. Browse career, "
        "learning and community stories from the controls here.",
    ),
    TourStep(
        "learning", "/learning", "Keep your career moving",
        "Explore links to learning resources from WHO, ICN and NMCN, or learn with "
        "colleagues in the community. External resources open in a new tab.",
    ),
    TourStep(
        "notifications", "/notifications", "Stay up to date",
        "Find updates about conversations, connection requests and opportunities. "
        "Use Preferences to choose the notifications you receive.",
    ),
    TourStep(
        "messages", "/messages", "Keep the conversation going",
        "Read and reply to private messages here. Once a connection is accepted, "
        "you can start a conversation from Network or the person’s profile.",
    ),
    TourStep(
        "employers", "/employers", "Build your next team",
        "Your employer account can post jobs and browse publicly shared candidate "
        "profiles. Use Post a job to describe a role and its application requirements.",
        role="employer",
    ),
    TourStep(
        "analytics", "/staff/users", "Understand how people use Nurse.ng",
        "Your staff dashboard shows unique users, daily activity and last recorded "
        "activity. Filter the overview by account type and date range to explore usage.",
        role="staff",
    ),
)


class TourConflict(ValueError):
    """The client must read the latest progress before making another change."""


def steps_for(user: User) -> list[TourStep]:
    return [step for step in STEPS if step.available_to(user)]


def _insert_offer(db: Session, user: User) -> bool:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(UserTour).values(
        user_id=user.id, status="offered", version=TOUR_VERSION,
        revision=0, offered_at=datetime.now(UTC),
    ).on_conflict_do_nothing(index_elements=[UserTour.user_id])
    return db.execute(statement).rowcount == 1


def offer_on_sign_in(db: Session, user: User) -> bool:
    """Call after successful, committed authentication, once per account.

    A tour-storage failure must not prevent sign-in. No existing preference is
    reset, including when a user ignores the invitation or the tour is updated.
    """
    try:
        offered = _insert_offer(db, user)
        db.commit()
        return offered
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Tour invitation could not be saved (%s).", type(exc).__name__)
        return False


def _current_index(row: UserTour, steps: list[TourStep]) -> int:
    keys = [step.key for step in steps]
    if row.step_key in keys:
        return keys.index(row.step_key)
    # A removed permission/feature must not leave a user on an inaccessible page.
    all_keys = [step.key for step in STEPS]
    if row.step_key in all_keys:
        position = all_keys.index(row.step_key)
        return next(
            (i for i, step in enumerate(steps) if all_keys.index(step.key) > position),
            len(steps) - 1,
        )
    return 0


def snapshot(db: Session, user: User) -> dict:
    steps = steps_for(user)
    row = db.get(UserTour, user.id, populate_existing=True)
    active = row is not None and row.status == "active"
    index = _current_index(row, steps) if active else None
    return {
        "steps": [step.public() for step in steps],
        "state": {
            "status": row.status if row else "available",
            "revision": row.revision if row else 0,
            "version": row.version if row else TOUR_VERSION,
            "run_id": str(row.run_id) if row and row.run_id else None,
            "index": index,
        },
    }


def transition(
    db: Session, user: User, *, action: str, revision: int,
    run_id: UUID | None, direction: str = "next",
) -> dict:
    """Compare-and-swap every change, including restarts and dismissal.

    Revisions fence duplicate requests and stale tabs; run IDs fence old browser
    history. In particular, a lost response can never advance two steps on retry.
    """
    if action not in {"start", "next", "previous", "skip", "finish", "unavailable"}:
        raise ValueError("Choose a supported tour action.")
    if direction not in {"next", "previous"}:
        raise ValueError("Choose a supported tour direction.")
    _insert_offer(db, user)
    row = db.get(UserTour, user.id, populate_existing=True)
    if row.revision != revision or row.run_id != run_id:
        db.rollback()
        raise TourConflict("Your tour has changed. Continue from your saved progress.")
    timestamp = datetime.now(UTC)
    steps = steps_for(user)
    values = {"revision": revision + 1}
    message = ""
    if action == "start":
        values.update(
            status="active", version=TOUR_VERSION, run_id=uuid4(), step_key=steps[0].key,
            started_at=timestamp, finished_at=None,
        )
    elif action == "skip" and row.status in {"offered", "active"}:
        values.update(status="skipped", finished_at=timestamp)
    elif row.status == "active":
        index = _current_index(row, steps)
        if action == "finish" and index == len(steps) - 1:
            values.update(status="completed", finished_at=timestamp)
        elif action in {"next", "previous", "unavailable"}:
            backwards = action == "previous" or (
                action == "unavailable" and direction == "previous"
            )
            destination = index + (-1 if backwards else 1)
            if 0 <= destination < len(steps):
                values["step_key"] = steps[destination].key
                if action == "unavailable":
                    message = "An unavailable section was passed over. Let’s continue here."
            elif action == "unavailable":
                # Do not claim completion when no final target can be shown.
                values.update(status="skipped", finished_at=timestamp)
                message = (
                    "There are no more available sections in this direction. "
                    "You can restart the tour in Account settings."
                )
            else:
                db.rollback()
                raise TourConflict("You’ve reached the end of this part of the tour.")
        else:
            db.rollback()
            raise TourConflict("Continue to the final step before finishing the tour.")
    else:
        db.rollback()
        raise TourConflict("This tour is no longer active. You can restart it in Account settings.")

    valid_user = exists(select(User.id).where(
        User.id == user.id, User.auth_version == user.auth_version,
        User.is_active.is_(True), User.status == UserStatus.ACTIVE,
        User.account_type == user.account_type, User.is_staff == user.is_staff,
    ))
    changed = db.execute(
        update(UserTour).where(
            UserTour.user_id == user.id, UserTour.revision == revision, valid_user,
        ).values(**values).execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise TourConflict("Your account or tour has changed. Refresh to continue.")
    db.commit()
    return {**snapshot(db, user), "message": message}
