# Community participation verification — 17 November 2026

This delivery completes voluntary peer support, recurring learning sessions,
newcomer introductions and welcomes, personal invitations with aggregate growth
counts, and optional weekly digests. It supports participation from the first
day of nursing school through clinical practice, research, education and
professorship. See the [member and operating guide](../../../COMMUNITY_PARTICIPATION.md).

## Python and native checks

[Final result summary](regression-results.json): **271 distinct Python cases
passed** across the final feature run and the related regressions below. These
are results from two runs, not a new combined execution.

| Report | Distinct cases | Result |
| --- | ---: | --- |
| [Final feature run](features.xml) | 50 | Passed |
| [Related cases from the combined run](related-regressions.xml) | 221 | Passed |

The related report extracts unchanged passing cases for authentication, provider
enrollment, notifications, workers, existing community growth, hosting, account
management, sharing and migration history from the
[original combined report](initial-combined-regression.xml). That original run
passed 270 cases and failed only the staff-name assertion described below. The
final 50-case feature run replaces its feature results; no failing related case
is omitted from the extracted report.

[Feature results](features.xml): **50 feature cases passed**, with no failures,
errors or skips. They cover access control, public-name privacy, consent, support
states and capacity, real introductions and welcomes, recurring scheduling,
private attendance, invitation attribution, digest eligibility and retries,
unsubscribe, staff report review, uploaded-field rejection and account deletion.

The [targeted final checks](staff-privacy-and-form-checks.xml) also passed both
staff privacy/review and uploaded-field rejection cases. These overlap the
50-case feature suite and are not additional distinct cases.

Four native Node tests passed using `npm test --prefix mobile`, including the
offline document build with the new templates. The sandbox prevented Node from
spawning Python; the same checks passed outside it. Ruff and parsing all 101
templates passed, as did the final whitespace check.

## Browser and accessibility

[Browser results](results.json) record the complete Chrome member journey:
support offer/request/acceptance and messaging connection, recurring session
creation and attendance, invitation registration and attribution, newcomer
introduction and host welcome, and verified-email digest opt-in.

All **36 selected axe/reflow states passed**, with no recorded JavaScript errors,
selected accessibility violations or horizontal overflow. The
[audit details](audits.json) cover 390px/light, 320px/dark with enlarged text,
and 1280px/light. Retained screenshots were visually inspected:

- [Phone support directory](support-390-light.png).
- [Narrow dark newcomer page](start-320-dark.png).
- [Desktop support directory](support-1280-light.png).

The narrow screenshot shows the page after navigation at its normal text size;
enlarged text was checked separately in the audit states. These selected checks
do not establish accessibility across every app page or every assistive device.

The [browser runner](../../../../tests/browser/participation.py) uses an isolated
SQLite database, disabled mail, local Chrome and axe-core. Its fixture public
domain is routed to local transport; this does not validate real public DNS,
TLS, hosted identity-provider callbacks or operating-system sharing on phones.

## PostgreSQL and local rollout

[PostgreSQL results](postgresql.json): an isolated PostgreSQL 18.6 cluster passed
fresh migration and metadata agreement, the existing hosted registration and
community journey, concurrent mentorship capacity acceptance, competing recurring
session workers, introductions/welcomes, private attendance, referral contribution
and returning-use counts, competing digest delivery claims and unsubscribe.
Digest mail used a private capture rather than SMTP.

CI now invokes the [participation journey](../../../../tests/hosting/participation_journey.py)
against PostgreSQL 16. That runner also executes the existing hosting journey.
The remote workflow and hosted provider/device checks have not been run here.

[Local rollout receipt](local-rollout.json): a private backup and an
upgrade/downgrade/upgrade rehearsal preceded upgrading local SQLite to
`e6480i9e5416`. All **13,589 existing rows across 53 tables** retained their data;
integrity and foreign-key checks passed. The web process and required worker
supervisor were restarted; readiness and eleven local HTTP checks passed.

The local app is available at
<http://127.0.0.1:8000/community/start>. The backup and runtime logs stay in the
Git-ignored `.local-backups` directory; no member database or runtime log is part
of this evidence directory.

## Earlier attempts and release limits

The [earlier 48-case feature run](initial-features.xml) passed before staff review
and uploaded-field rejection coverage was added. An initial staff test used
`"PRIVATE NAME"` as its forbidden string and matched the staff member's own
account header. Its final assertions check the other participants' full names;
the staff report still includes the reported goal, as intended. Both targeted
checks and the full 50-case feature suite then passed.

Early browser attempts had selector and fixture assumptions corrected before
the complete passing journey. A sandboxed combined regression stalled and was
terminated before a complete report; it supplies no passing evidence.
An [earlier related run](earlier-related-regression.xml) failed a recovery-email
logging assertion because Alembic disabled the existing application logger.
Preserving existing loggers fixed that behavior; the corresponding case passed
in the final related results. This earlier report is retained as an initial
attempt, not a passing receipt.

The local installation has no configured public sharing origin. Public
invitations require reachable HTTPS hosting in `NURSE_NG_PUBLIC_BASE_URL`, and
digest delivery requires mail configuration and each member's verified-email
opt-in. The new private management forms require online access. Actual member
adoption and retention need a public rollout and observed participation;
isolated checks do not establish market penetration.

No public deployment, real invitations, real-member email, commit or push
occurred during this delivery.
