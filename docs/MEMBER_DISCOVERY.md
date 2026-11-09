# Member discovery and onboarding

Implemented 9 November 2026 as roadmap priority 4. This extends the existing profiles,
field visibility, directory, follows, connections and opportunity services. No external
search service, AI provider, worker, or new application dependency is required.

## Member journey

- Registration signs the member in and opens `/welcome`. Step 1 offers up to six
  professional interests and an optional profile location, with a privacy explanation.
- Saving opens `/welcome/discover`, with visible success feedback, people to meet and
  current opportunities. Members can skip without creating a profile and return later.
- The dashboard offers onboarding to existing members, shows people/opportunity
  suggestions, and links to edit interests. The account menu also includes My interests.
- `/nurses` supports case-insensitive public-name/headline/skill/interest/location search,
  combined location, interest and career-stage filters, and 12 profiles per page.
  Pagination keeps the selected filters; no matches offers a clear reset action.
- Find people appears in desktop navigation and the mobile menu. The network page links
  to both the directory and personal suggestions. A member opens a public profile to
  use the existing Follow and Connect actions; neither happens automatically.
- Interests are also editable on the professional profile and have their own row in
  sharing controls. They appear on public profiles and cards only when explicitly shared.

## Privacy and recommendations

New profiles remain drafts and undiscoverable. No new public field-visibility rows are
created by onboarding. Profile location and interests use the existing field-level
sharing system, so existing public fields remain public and the welcome page explains
that updates will be visible. No profile is automatically published. Photo sharing,
opportunity alerts and email consent remain separate and unchanged.

Directory filtering and result counts enforce field visibility in SQL. Candidate ranking
also uses only public fields of other members. Private, unpublished, inactive or suspended
members are excluded. Another member's private location, skills or interests cannot cause
that person to match a search or receive a higher suggestion ranking. The existing avatar
renderer and photo endpoint retain photo-access enforcement.

The signed-in member's own interests and location can inform their recommendations even
when private. Shared public interests rank ahead of location matches; self, followed
members and pending/accepted connections are excluded. Otherwise, public profiles are
suggested without claiming a shared interest. Ranking is deterministic and explanations
appear on cards.

Opportunity suggestions use the existing open-job and source-freshness rules. Interest
terms and location match current jobs, with Nigerian opportunities first. If none match,
the page clearly offers current openings instead. These suggestions do not overwrite the
separate matching/notification preferences at `/jobs/preferences` or turn on emails.

## Deployment

Apply the ordinary migration before starting the updated app:

```sh
venv/bin/alembic upgrade head
```

Revision `c426ed871b03` follows `b715a203ce46`. It adds an empty, private-by-default
`nurse_profiles.interests` string and nullable `users.onboarding_completed_at`. Existing
profiles, field visibility, photos, saved opportunities and notification settings are
preserved. The downgrade refuses to discard saved interests or onboarding progress.

The local development database was backed up, migrated on a clone and compared against
all original table columns before applying the migration locally. Foreign keys and
Alembic metadata checks passed. Production migration/deployment and real-device checks
remain part of the hosting and quality roadmap priorities.

## Verification

- `tests/test_member_discovery.py`: hidden-field search/count/rank protection, combined
  filters, escaped wildcard characters, pagination, inactive/private members, photo
  visibility, optional/resumable onboarding, CSRF/authentication, atomic input validation,
  preservation of sharing and alerts, and current Nigerian-first opportunity suggestions.
- Existing profile, sharing, registration, community, account-photo and opportunity tests
  remain part of regression coverage.
- `tests/browser/member_discovery.py`: isolated SQLite database and local Chrome journey
  through registration, onboarding feedback, suggestions, filters, pagination, privacy,
  mobile navigation, following, connection requests and dashboard. Checks widths 320,
  390 and 1280, plus dark theme and enlarged text; sends no real email.

Local results: 23 focused tests passed; all 516 collected regression tests were covered
across the interrupted combined run and two completed batches (141 and 131 tests).
The complete browser journey passed, with artifacts at
`/tmp/nurse-discovery-browser-4pyakrt4`. Ruff and whitespace checks passed.

Commands:

```sh
venv/bin/python -m pytest tests/test_member_discovery.py
venv/bin/python tests/browser/member_discovery.py
```

The initial implementation uses a curated vocabulary of twelve interests and simple,
explainable matching. It does not infer private interests or claim that a suggested
opportunity establishes eligibility. Availability depends on actual published profiles
and current opportunities; empty states reflect that honestly.
