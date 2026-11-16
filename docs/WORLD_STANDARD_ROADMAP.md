# Nurse.ng: seven priorities for a world-standard app

Recorded: 8 November 2026, following the user's request to preserve the seven-point assessment.

## Current direction — 16 November 2026

The immediate product goal is an inclusive nursing community and sustained
community growth. Nurses across career stages should be able to belong,
connect, exchange opportunities and support professional development. Current
recommendations prioritize joining, first meaningful participation, sharing,
invitations and reasons to return.

Employer capabilities are a later expansion once the community is established
and trusted. Staff MFA remains explicitly deferred by the user. It is pending
work, rather than the next immediate product priority. The seven engineering
priorities below remain a reference; the delivery sequence at the end follows
this updated direction. See [community growth and authorized expansion
scope](COMMUNITY_EXPANSION.md).

Nurse.ng has a functional foundation: accounts, professional profiles, opportunities,
applications, community discussions, messaging and Reels. The main remaining work is
dependable operation, trustworthy opportunities and a smoother experience that gives
members reasons to return.

These priorities describe remaining work and recommended sequencing. Recording an item
does not mark it implemented. The assessment draws on the code and locally tested flows;
production performance and public-launch readiness still need deployment evidence.

## 1. Reliable public hosting and recovery

**Priority: before public launch.**

The current app uses local storage and separately started workers. Production configuration
safeguards and local database backups already exist, but a running development environment
does not establish reliable public hosting or recovery.

Remaining work:

- Configure production hosting, a public domain and HTTPS, and verify the deployed settings.
- Provide persistent media storage and CDN delivery, with appropriate protection for private files.
- Supervise background workers so they start automatically and recover after failures.
- Add uptime/error monitoring and automated checks for staging and production releases.
- Verify PostgreSQL migrations, concurrent use and worker recovery.
- Test restoring both database and media backups, and record a repeatable recovery procedure.

## 2. Stronger trust and account protection

**Priority: support community trust throughout growth; employer requirements
apply before employer expansion. Staff MFA is deferred by the user.**

Email verification, password recovery, authenticated password changes, account deletion and
session invalidation after password reset are implemented. Employer registration currently
allows members to select the employer role themselves; that does not establish organisation
legitimacy.

Remaining work:

- Maintain and extend employer organization/representative checks and approval
  boundaries when expanding job publishing, applications and applicant-data access.
- Track staff two-factor authentication as deferred work for a later hardening phase.
- Give members device/session management and controls to block other users.
- Keep email verification, document review and confirmed professional credentials clearly
  distinguished in labels and explanations.

Authoritative professional-credential verification remains a separate unresolved product
decision. Existing document review must not imply that an official professional register
has confirmed a person's credentials.

## 3. More reliable coverage of Nigerian opportunities

**Status: implemented and verified locally; source coverage continues to expand.**

Nigerian-first ordering and discovery scheduling remain in place. The collector now supports
ordinary HTML announcements and bounded links within approved source scope, alongside
structured job data. Additional Nigerian public-health discovery candidates and a staff
coverage dashboard expose gaps by source type and recorded location.

Members can save opportunities, choose deadline reminders, set interests and receive new
matching alerts through the notification system. Extra location filters are available without
restoring the removed mobile filter buttons. Source permissions, freshness, deadline checks
and review of ambiguous fields remain enforced.

Still required for sustained live coverage:

- Maintain source availability and monitor automatically verified publishers; review genuinely uncertain identities.
- Continue adding and reconfirming federal/state, private and early-career announcements.
- Add adapters for sources that publish only documents/images or require browser interaction.
- Monitor collection success and current openings; a registered programme is not evidence
  that it is accepting applications.

The 9 November worker run activated NCDC monitoring and published a current EHA Clinics medical vacancy through the ordinary HTML/factual-indexing path. General web search now works through self-hosted SearXNG without a Brave API key. See [search and source operations](SEARCH_DISCOVERY.md) and [Nigerian opportunities](NIGERIAN_OPPORTUNITIES.md) for evidence and limits.

## 4. Easier member discovery and onboarding

**Status: implemented locally; production deployment remains part of priority 1.**

The directory supports search, location, professional-interest and career-stage filters,
with stable pagination. “Find people” is available in the main navigation and mobile menu,
with links from the dashboard and network page.

New accounts enter a short, optional welcome flow to choose up to six interests and a
location, understand visibility, and discover people and opportunities. Existing members
can start or revisit it from the dashboard or account menu. Suggestions use shared public
interests and locations; opportunity suggestions keep Nigerian opportunities first.

Profiles and photos remain private by default. Filtering, counts and ranking cannot use
another member's hidden fields. Onboarding preserves existing sharing, photo and alert
choices, and does not automatically follow anyone or send connection requests.

See [member discovery and onboarding](MEMBER_DISCOVERY.md) for behavior, verification and
migration requirements. Real-device and assistive-technology testing remain under priority 6.

## 5. A proper notification system and better messaging

**Status: implemented locally; production operation remains part of priority 1.**

The LinkedIn-style notification inbox now includes unread badges, category filters,
read controls and per-category in-app/email preferences. Replies, connections,
messages and application changes create transactional notifications. Email is opt-in,
requires a verified address, and uses a persistent worker queue with retry and recovery.

Conversations update automatically while visible, preserve drafts and reading position,
show send/retry feedback and load older messages beyond the former 100-message limit.
Idempotent sends protect against duplicate messages after a lost response. Existing
connection and source-visibility permissions are rechecked throughout.

See [notifications and messaging](NOTIFICATIONS.md) for the implementation, tests,
worker command and precise limits. Production worker supervision, operational monitoring
and physical-device validation remain under priorities 1 and 6. Device push is not
part of the selected in-app plus optional-email channels.

## 6. Consistent quality across the whole app

**Priority: throughout development, with essential checks before public launch.**

Visible account feedback, display preferences, responsive layouts and Reels processing are
already implemented. Reels include a smaller data-saving playback version and support
creator-provided captions.

The 9 November quality increment extends shared feedback to ordinary forms across
member and staff journeys, implements event publishing/RSVPs/calendar downloads,
and connects the existing Google/LinkedIn controls to provider integrations.
Provider credentials and live sign-in validation are still required. See
[quality verification](QUALITY_VERIFICATION.md), [events](EVENTS.md) and
[social sign-in setup](SOCIAL_SIGN_IN.md).

Remaining work:

- Verify the expanded success, failure and pending feedback against real-device journeys.
- Test complete journeys on real Android phones and iPhones, including Safari and slow connections.
- Test screen-reader use, keyboard navigation and enlarged text across the main journeys.
- Finish provider configuration and verify visible controls across all roles and devices.
- Consider adaptive video streaming and automatic captions as later Reels improvements.

Local automated and browser checks are valuable evidence, but do not replace testing with
real devices and assistive technologies.

## 7. Evidence from real users and a support process

**Priority: prepare before the pilot, then use the findings to guide development.**

Working features and passing tests establish functionality. Product value needs evidence
from the people who will use Nurse.ng.

The staff [user analytics dashboard](MEMBER_ANALYTICS.md) now records daily use,
recent activity and distinct 7/30-day participation, with account IDs and daily
history. These are usage measurements for existing accounts; an observed pilot,
application outcomes and support performance still need their own evidence.

Remaining work:

- Run a community pilot with nurses across career stages, students and opportunity seekers.
- Measure first meaningful participation, useful exchanges, opportunity discovery,
  returning members and invitations that result in participation. Establish baselines
  and add missing instrumentation before treating these as measured outcomes.
- Observe where people abandon tasks or need help, and use those findings to set priorities.
- Establish who handles support, reports, appeals and failed uploads, with clear response targets.
- Set pilot targets and a measurement period before evaluating the results.

## Recommended sequence

1. Prioritize community growth: easy joining, relevant discovery, a first useful
   exchange and convenient sharing/invitations.
2. Give members reasons to return through conversations, replies, opportunities
   and professional development, with controlled notifications and moderation.
3. Use a supported community pilot and participation/retention evidence to guide
   improvements and market penetration. Maintain dependable operation throughout.
4. Introduce employer capabilities gradually once the community is established
   and trusted, with their required approval, access and operational protections.

This sequence is a recommendation, not a claim that the remaining items are completed.
Some older build-plan tracker entries predate the account and Reels work; update their
status against implementation evidence rather than treating completed features as missing.

## Related records

- [Build plan and assessment tracker](BUILD_PLAN.md#assessment-baseline-and-completion-tracker--6-november-2026)
- [Account management and email delivery](ACCOUNT_MANAGEMENT.md)
- [Recruitment-source operations](RECRUITMENT_SOURCE_OPERATIONS.md)
- [Reels operations and deployment limitations](REELS.md)
- [Decisions](DECISIONS.md) and [work log](WORK_LOG.md)
