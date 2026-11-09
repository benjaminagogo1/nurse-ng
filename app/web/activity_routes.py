"""Staff account analytics and authenticated activity signals."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services import activity as service
from app.web.deps import require_staff, require_user, verify_csrf
from app.web.templating import render, templates

router = APIRouter(tags=["activity"])


@router.post("/activity/pulse")
def activity_pulse(
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    recorded = service.record_visit(db, user)
    return Response(status_code=204 if recorded else 503, headers={"Cache-Control": "no-store"})


def dashboard_context(
    account_type: str = "nurse",
    include_staff: bool = False,
    days: int = 14,
    q: Annotated[str, Query(max_length=120)] = "",
    activity: str = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if (
        account_type not in service.ACCOUNT_TYPES
        or activity not in service.ACTIVITY_FILTERS
        or days not in {7, 14, 30}
    ):
        raise HTTPException(
            status_code=400, detail="Choose a listed account type and activity range."
        )
    timestamp = service.now()
    query = q.strip()
    members = service.member_activity(
        db,
        account_type=account_type,
        include_staff=include_staff,
        query=query,
        activity=activity,
        page=page,
        at=timestamp,
    )

    def page_url(number=1, **changes):
        return "/staff/users?" + urlencode(
            {
                "account_type": account_type,
                "include_staff": int(include_staff),
                "days": days,
                "q": query,
                "activity": activity,
                "page": number,
                **changes,
            }
        )

    report = service.activity_report(
        db, account_type=account_type, include_staff=include_staff, days=days, at=timestamp
    )
    history = list(reversed(report["history"]))
    maximum = max(4, ((max((day["count"] for day in history), default=0) + 3) // 4) * 4)
    points = [
        {
            **day,
            "x": round(44 + i * 642 / (len(history) - 1), 2) if len(history) > 1 else 365,
            "y": round(178 - day["count"] / maximum * 150, 2),
        }
        for i, day in enumerate(history)
    ]
    line = " ".join(f"{'M' if i == 0 else 'L'}{p['x']},{p['y']}" for i, p in enumerate(points))
    area = f"{line} L{points[-1]['x']},178 L{points[0]['x']},178 Z" if len(points) > 1 else ""
    return {
        "title": "User analytics",
        "page": "staff-users",
        "user": user,
        "report": report,
        "include_staff": include_staff,
        "days": days,
        "chart": {
            "points": points,
            "line": line,
            "area": area,
            "ticks": [{"count": maximum * i // 4, "y": 178 - i * 37.5} for i in range(5)],
        },
        "members": members,
        "account_type": account_type,
        "query": query,
        "activity": activity,
        "account_types": service.ACCOUNT_TYPES,
        "activity_filters": service.ACTIVITY_FILTERS,
        "previous_page": page_url(members["page"] - 1) if members["page"] > 1 else None,
        "next_page": page_url(members["page"] + 1) if members["page"] < members["pages"] else None,
        "reset_url": page_url(q="", activity="all"),
        "metric_urls": {
            key: page_url(activity=key, q="") for key in ["all", "recent", "today", "week", "month"]
        },
        "range_urls": {number: page_url(days=number) for number in [7, 14, 30]},
    }


@router.get("/staff/users")
def users_and_activity(request: Request, context: dict = Depends(dashboard_context)):
    return render(request, "staff/users.html", context)


@router.get("/staff/users/data", response_class=HTMLResponse)
def dashboard_data(context: dict = Depends(dashboard_context)):
    # This background refresh is deliberately outside the page-visit recorder.
    return HTMLResponse(
        templates.get_template("staff/_activity_dashboard.html").render(context),
        headers={"Cache-Control": "no-store"},
    )
