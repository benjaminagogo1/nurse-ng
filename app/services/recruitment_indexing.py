"""Staff-selected factual sources and their bounded collection addresses.

Factual indexing and full-content reuse have different authorization scopes.
Collection addresses must match the stored publisher scope. Search results
cannot choose arbitrary fetch destinations or broaden staff-selected authority.
"""

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import update

from app.models.recruitment import RecruitmentSource
from app.services.recruitment_fetch import in_scope, origin, public_url


def https_url(value: str) -> str:
    parsed = urlsplit(public_url(value))
    return urlunsplit(parsed._replace(scheme="https", fragment=""))


def scope_aliases(prefix: str) -> tuple[str, ...]:
    """An approved HTTPS site and its conventional www alias, with the same path."""
    parsed = urlsplit(public_url(prefix))
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        return ()
    host = parsed.hostname or ""
    alternate = host.removeprefix("www.") if host.startswith("www.") else "www." + host
    return (prefix, urlunsplit(parsed._replace(netloc=alternate)))


def matching_scope(url: str, prefix: str) -> str:
    return next((scope for scope in scope_aliases(prefix) if in_scope(url, scope)), "")


def configuration(source, *, scope: str = "") -> tuple[str, str]:
    """Keep the submitted URL intact; collect its HTTPS address within this publisher."""
    requested = https_url(source.original_url)
    collection_url = requested
    publisher_scope = origin(requested) + "/"
    if source.observed_url and matching_scope(source.observed_url, publisher_scope):
        collection_url = source.observed_url
    prefix = public_url(scope) if scope else origin(collection_url) + "/"
    # A shared recruitment portal must retain the submitted tenant/path boundary.
    if not scope and (urlsplit(collection_url).hostname or "") in {
        "recruiting.paylocity.com", "jobs.lever.co", "boards.greenhouse.io",
        "job-boards.greenhouse.io", "apply.workable.com", "jobs.smartrecruiters.com",
    }:
        prefix = urlunsplit(urlsplit(collection_url)._replace(query="", fragment=""))
    if not matching_scope(requested, prefix) or not matching_scope(collection_url, prefix):
        raise ValueError("The collection scope must cover this source on its HTTPS website.")
    return collection_url, prefix


def staff_index_authorized(source) -> bool:
    review = source.activation_review or {}
    evidence = review.get("evidence", {})
    try:
        return bool(
            source.approval_mode == "staff"
            and review.get("status") == "staff_approved"
            and evidence.get("identity_basis") == "staff_selection"
            and evidence.get("staff_id")
            and evidence.get("mode") == "factual_index"
            and evidence.get("requested_url") == source.original_url
            and evidence.get("scope") == source.reuse_url_prefix
            and matching_scope(https_url(source.original_url), source.reuse_url_prefix)
            and in_scope(evidence.get("collection_url", ""), source.reuse_url_prefix)
        )
    except ValueError:
        return False


def accept_collection_address(source, observed_url: str) -> bool:
    """Resolve HTTPS/www aliases without granting access to another publisher."""
    if not staff_index_authorized(source):
        return False
    prefix = matching_scope(observed_url, source.reuse_url_prefix)
    if not prefix:
        return False
    source.reuse_url_prefix = prefix
    source.vacancy_url_prefix = prefix
    source.activation_review = {
        **source.activation_review,
        "evidence": {
            **source.activation_review["evidence"],
            "scope": prefix,
            "collection_url": observed_url,
            "recruitment_page": observed_url,
        },
    }
    return True


def select_collection_channel(db, source, url, *, dry_run=False):
    """Operator configuration within an existing factual approval; never grant new scope."""
    from app.services.recruitment import RecruitmentError, event, now
    from app.services.vacancies import collector_authorized

    if not collector_authorized(source) or not staff_index_authorized(source):
        raise RecruitmentError("Choose a currently approved staff-selected factual source.")
    channel = public_url(url)
    if not in_scope(channel, source.reuse_url_prefix):
        raise RecruitmentError("The channel must be within the source's existing approved scope.")
    previous = source.activation_review['evidence'].get('collection_channel', '')
    result = {'source': source.original_url, 'previous_channel': previous,
              'collection_channel': channel, 'changed': previous != channel, 'dry_run': dry_run}
    if not dry_run and previous != channel:
        review = {**source.activation_review, 'evidence': {
            **source.activation_review['evidence'], 'collection_channel': channel,
        }}
        changed = db.execute(
            update(RecruitmentSource)
            .where(RecruitmentSource.id == source.id, RecruitmentSource.revision == source.revision)
            .values(activation_review=review, revision=source.revision + 1, next_check_at=now())
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise RecruitmentError("This source changed. Reload it before selecting a channel.")
        event(db, source, 'collection_channel_selected', reference=channel, details={
            'previous_channel': previous, 'configuration_method': 'operator_cli',
            'note': 'Selected a recruitment channel within the existing factual collection scope.',
        })
        db.commit()
        db.refresh(source)
    return result
