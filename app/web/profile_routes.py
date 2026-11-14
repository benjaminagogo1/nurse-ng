"""Nurse profile pages: view, edit, activation, sharing, and the public page."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.profile import NurseProfile, ProfessionalStatus, ProfileStatus, Visibility
from app.models.user import User
from app.services.member_interests import INTEREST_OPTIONS
from app.services.profiles import (
    PROFESSIONAL_STATUS_LABELS,
    SHAREABLE_FIELDS,
    ProfileError,
    activate_profile,
    deactivate_profile,
    get_active_profile_by_public_id,
    get_profile_for_user,
    get_visibility_map,
    professional_status_label,
    public_profile_fields,
    save_profile,
    save_sharing_settings,
)
from app.services.verification import (
    EvidenceUpload,
    VerificationError,
    has_pending_case,
    list_cases_for_profile,
    submit_case,
)
from app.web.community_routes import profile_social_context
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/profile", tags=["profile"])
public_router = APIRouter(tags=["public"])


def _form_values(profile: NurseProfile | None, **overrides: str) -> dict[str, str]:
    values = {
        "display_name": profile.display_name if profile else "",
        "headline": profile.headline if profile else "",
        "location": profile.location if profile else "",
        "bio": profile.bio if profile else "",
        "professional_status": (
            profile.professional_status
            if profile
            else ProfessionalStatus.STUDENT.value
        ),
        "qualification": profile.qualification if profile else "",
        "years_experience": (
            str(profile.years_experience)
            if profile and profile.years_experience is not None
            else ""
        ),
        "skills": profile.skills if profile else "",
        "interests": profile.interests if profile else "",
    }
    values.update(overrides)
    return values


def _sharing_items(
    profile: NurseProfile,
    visibility: dict[str, str],
) -> list[dict[str, str]]:
    items = []
    for name, label in SHAREABLE_FIELDS:
        value = getattr(profile, name)
        if name == "professional_status":
            value = professional_status_label(value)
        items.append(
            {
                "name": name,
                "label": label,
                "visibility": visibility.get(name, Visibility.PRIVATE.value),
                "preview": "" if value is None else str(value),
            }
        )
    return items


def _show_context(
    request: Request,
    profile: NurseProfile,
    db: Session,
    *,
    error: str | None = None,
) -> dict[str, object]:
    visibility = get_visibility_map(db, profile)
    is_active = profile.status == ProfileStatus.ACTIVE
    share_url = (
        str(request.url_for("public_profile", public_id=str(profile.public_id)))
        if is_active
        else None
    )
    return {
        "profile": profile,
        "status_label": professional_status_label(profile.professional_status),
        "is_active": is_active,
        "share_url": share_url,
        "public_field_count": sum(
            1 for value in visibility.values() if value == Visibility.PUBLIC.value
        ),
        "display_name_shared": visibility.get("display_name") == Visibility.PUBLIC.value,
        **_document_review_context(profile),
        "error": error,
    }


def _document_reviewed_on(profile: NurseProfile) -> str | None:
    value = profile.document_reviewed_at
    return value.strftime("%d %B %Y") if value else None


def _document_review_context(profile: NurseProfile) -> dict[str, object]:
    reviewed_name = profile.document_reviewed_name
    current_name = (profile.display_name or "").strip()
    return {
        "document_reviewed_on": _document_reviewed_on(profile),
        "document_reviewed_name": reviewed_name,
        "document_review_name_changed": bool(
            reviewed_name and current_name and reviewed_name != current_name
        ),
    }


def _verification_context(
    db: Session,
    profile: NurseProfile | None,
    *,
    registration_number: str = "",
    error: str | None = None,
) -> dict[str, object]:
    if profile is None:
        return {"title": "Verification", "profile": None, "error": error}
    return {
        "title": "Document review",
        "profile": profile,
        "cases": list_cases_for_profile(db, profile.id),
        "pending": has_pending_case(db, profile.id),
        **_document_review_context(profile),
        "registration_number": registration_number,
        "max_megabytes": max(1, settings.evidence_max_bytes // (1024 * 1024)),
        "evidence_retention_days": settings.evidence_retention_days,
        "evidence_pending_retention_days": settings.evidence_pending_retention_days,
        "error": error,
        "allow_extra_evidence": True,
    }


@router.get("")
def show_profile(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return RedirectResponse("/profile/edit", status_code=status.HTTP_303_SEE_OTHER)

    return render(
        request,
        "profile/show.html",
        {"title": "Your profile", "user": user, **_show_context(request, profile, db)},
    )


@router.get("/edit")
def edit_profile_form(
    request: Request,
    return_to: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    prefill = {"display_name": user.full_name} if profile is None and user.full_name else {}
    return render(
        request,
        "profile/edit.html",
        {
            "title": "Edit your profile",
            "user": user,
            "profile": profile,
            "values": _form_values(profile, **prefill),
            "return_to": "verification" if return_to == "verification" else "",
            "status_options": list(PROFESSIONAL_STATUS_LABELS.items()),
            "interest_options": INTEREST_OPTIONS,
        },
    )


@router.post("/edit")
def save_profile_form(
    request: Request,
    display_name: str = Form(""),
    headline: str = Form(""),
    location: str = Form(""),
    bio: str = Form(""),
    professional_status: str = Form(""),
    qualification: str = Form(""),
    years_experience: str = Form(""),
    skills: str = Form(""),
    interests: list[str] = Form([]),
    return_to: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    try:
        save_profile(
            db,
            user,
            display_name=display_name,
            headline=headline,
            location=location,
            bio=bio,
            professional_status=professional_status,
            qualification=qualification,
            years_experience=years_experience,
            skills=skills,
            interests=", ".join(interests),
        )
    except ProfileError as exc:
        profile = get_profile_for_user(db, user.id)
        return render(
            request,
            "profile/edit.html",
            {
                "title": "Edit your profile",
                "user": user,
                "profile": profile,
                "values": _form_values(
                    profile,
                    display_name=display_name,
                    headline=headline,
                    location=location,
                    bio=bio,
                    professional_status=professional_status,
                    qualification=qualification,
                    years_experience=years_experience,
                    skills=skills,
                    interests=", ".join(interests),
                ),
                "status_options": list(PROFESSIONAL_STATUS_LABELS.items()),
                "interest_options": INTEREST_OPTIONS,
                "error": str(exc),
                "return_to": "verification" if return_to == "verification" else "",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Keep the continuation local to this form and allow only a named destination.
    continuing_verification = return_to == "verification"
    return redirect_feedback(
        request, "/profile/verification" if continuing_verification else "/profile",
        message(
            'Profile saved',
            'You can now submit your documents for review.' if continuing_verification
            else 'Your profile details have been saved.',
        ),
    )


@router.get("/sharing")
def sharing_form(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return RedirectResponse("/profile/edit", status_code=status.HTTP_303_SEE_OTHER)

    visibility = get_visibility_map(db, profile)
    return render(
        request,
        "profile/sharing.html",
        {
            "title": "Sharing controls",
            "user": user,
            "profile": profile,
            "items": _sharing_items(profile, visibility),
            "is_active": profile.status == ProfileStatus.ACTIVE,
        },
    )


@router.post("/sharing")
def save_sharing_form(
    request: Request,
    visibility_display_name: str = Form(Visibility.PRIVATE.value),
    visibility_professional_status: str = Form(Visibility.PRIVATE.value),
    visibility_headline: str = Form(Visibility.PRIVATE.value),
    visibility_location: str = Form(Visibility.PRIVATE.value),
    visibility_bio: str = Form(Visibility.PRIVATE.value),
    visibility_qualification: str = Form(Visibility.PRIVATE.value),
    visibility_years_experience: str = Form(Visibility.PRIVATE.value),
    visibility_skills: str = Form(Visibility.PRIVATE.value),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return RedirectResponse("/profile/edit", status_code=status.HTTP_303_SEE_OTHER)

    submitted = {
        "display_name": visibility_display_name,
        "professional_status": visibility_professional_status,
        "headline": visibility_headline,
        "location": visibility_location,
        "bio": visibility_bio,
        "qualification": visibility_qualification,
        "years_experience": visibility_years_experience,
        "skills": visibility_skills,
    }

    try:
        save_sharing_settings(db, profile, submitted)
    except ProfileError as exc:
        safe_view = {
            name: (
                value
                if value in {Visibility.PRIVATE.value, Visibility.PUBLIC.value}
                else Visibility.PRIVATE.value
            )
            for name, value in submitted.items()
        }
        return render(
            request,
            "profile/sharing.html",
            {
                "title": "Sharing controls",
                "user": user,
                "profile": profile,
                "items": _sharing_items(profile, safe_view),
                "is_active": profile.status == ProfileStatus.ACTIVE,
                "error": str(exc),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return redirect_feedback(
        request, "/profile",
        message(
            'Sharing choices saved',
            'Your selected fields now use these visibility settings.',
        ),
    )


@router.get("/verification")
def verification_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    return render(
        request,
        "profile/verification.html",
        {"user": user, **_verification_context(db, profile)},
    )


@router.post("/verification")
def submit_verification(
    request: Request,
    registration_number: str = Form(""),
    licence: UploadFile | None = File(None),
    government_id: UploadFile | None = File(None),
    nursing_certificate: UploadFile | None = File(None),
    additional_certification: UploadFile | None = File(None),
    consent: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return render(
            request,
            "profile/verification.html",
            {"user": user, **_verification_context(
                db, None,
                error="Create and save your profile before submitting documents for review.",
            )},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if consent != "on":
        return render(
            request,
            "profile/verification.html",
            {
                "user": user,
                **_verification_context(
                    db,
                    profile,
                    registration_number=registration_number,
                    error="Consent is required before we can store and review documents.",
                ),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    limit = settings.evidence_max_bytes + 1

    def _read(upload: UploadFile | None) -> EvidenceUpload:
        if upload is None or not upload.filename:
            return EvidenceUpload(data=b"", filename="")
        return EvidenceUpload(data=upload.file.read(limit), filename=upload.filename)

    try:
        submit_case(
            db,
            user=user,
            profile=profile,
            registration_number=registration_number,
            licence=_read(licence),
            government_id=_read(government_id),
            nursing_certificate=_read(nursing_certificate),
            additional_certification=_read(additional_certification),
        )
    except VerificationError as exc:
        return render(
            request,
            "profile/verification.html",
            {
                "user": user,
                **_verification_context(
                    db,
                    profile,
                    registration_number=registration_number,
                    error=str(exc),
                ),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return redirect_feedback(
        request, "/profile/verification",
        message(
            'Documents submitted',
            'Your documents are waiting for review. You can check progress here.',
        ),
    )



@router.post("/activate")
def activate(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return RedirectResponse("/profile/edit", status_code=status.HTTP_303_SEE_OTHER)

    try:
        activate_profile(db, user, profile)
    except ProfileError as exc:
        return render(
            request,
            "profile/show.html",
            {
                "title": "Your profile",
                "user": user,
                **_show_context(request, profile, db, error=str(exc)),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return redirect_feedback(
        request, "/profile",
        message(
            'Profile is public',
            'Your profile is now discoverable with only the fields you chose to share.',
        ),
    )


@router.post("/deactivate")
def deactivate(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        return RedirectResponse("/profile/edit", status_code=status.HTTP_303_SEE_OTHER)

    deactivate_profile(db, profile)
    return redirect_feedback(
        request, "/profile",
        message(
            'Profile is private',
            'Your profile is no longer listed publicly.',
        ),
    )


@public_router.get("/p/{public_id}", name="public_profile")
def public_profile(
    public_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        identifier = uuid.UUID(public_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None

    profile = get_active_profile_by_public_id(db, identifier)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    fields = public_profile_fields(db, profile)
    response = render(
        request,
        "profile/public.html",
        {
            "title": f"{fields.get('display_name', 'Nurse profile')} — Nurse.ng",
            "user": user,
            "fields": fields,
            "profile_public_id": profile.public_id,
            "profile_owner": profile.user,
            **_document_review_context(profile),
            **profile_social_context(db, user, profile),
        },
    )
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
