# Hosting readiness verification — 17 November 2026

This increment replaces development-origin sharing with configured public HTTPS
links and adds portable production startup and deployment instructions. It does
not deploy a public site.

## Automated regression

All **961 Python tests passed**, with no failures, errors or skips. The final
suite ran in six isolated groups after an earlier long run was terminated with
SIGTERM before producing a complete report. A profile-sharing fixture was also
updated to supply a public origin rather than expect a loopback share link.

| Report | Cases | Result |
| --- | ---: | --- |
| [Group 1](regression-1.xml) | 139 | Passed |
| [Group 2](regression-2.xml) | 117 | Passed |
| [Group 3](regression-3.xml) | 163 | Passed |
| [Group 4](regression-4.xml) | 153 | Passed |
| [Group 5](regression-5.xml) | 199 | Passed |
| [Group 6](regression-6.xml) | 190 | Passed |

This covers the entire collected pytest suite, including production configuration,
community sharing, profiles, recovery/mail, social authentication, notifications,
workers, migration history and offline behavior. The PDF safety fixture emits
an existing pypdf deprecation warning; it passes. Ruff, dependency consistency
and whitespace checks passed.

## PostgreSQL and application journey

[PostgreSQL receipt](postgresql.json): PostgreSQL 18.6 on an isolated temporary
cluster; fresh migrations through `e6480g7c3294`, no schema drift, registration,
member-created community and membership, question, public invitation, signup
continuation, reply, readiness and Secure cookies passed. Database URLs with
percent-encoded credential characters were included. The server was stopped
and its temporary cluster removed afterward.

The check exposed and resolved incompatible integer Boolean defaults in three
historical migrations, a redundant community-slug uniqueness constraint, and
ConfigParser interpolation of percent signs in database URLs. Existing live
databases were not migrated or changed during this work. The unique slug index
remains in place. CI repeats the journey against PostgreSQL 16 with an encoded
test password.

The retained runner is [postgres_journey.py](../../../../tests/hosting/postgres_journey.py).
It requires an explicitly isolated database named `nurse_ng_hosting_test`,
disables mail, uses temporary storage and never sends actual invitations.

## Browser and native configuration

[Browser results](browser/results.json) and [accessibility/reflow audits](browser/audits.json):
community creation, explicit composer selection, joining, questions/replies,
Helpful/selected answers, invitation signup continuation, WhatsApp/native/copy
sharing and fallbacks, activity drafts and offline synchronization passed.
All 36 selected axe/reflow states passed at 390px/light, 320px/dark with enlarged
text, and 1280px/light, with no recorded JavaScript exceptions. Retained
screenshots were visually inspected:

- [Phone](browser/activity-390-light.png).
- [Narrow phone with enlarged text](browser/activity-320-dark.png).
- [Desktop](browser/activity-1280-light.png).

Shared links use `https://members.nurse.example`. Browser navigation maps that
fixture domain to isolated local transport; it does not establish real DNS,
TLS, provider callbacks or native operating-system sharing on a public device.

[Mobile results](mobile.json): four Node tests passed, including public release
origin validation and actual offline document generation. The template URL
change initially broke router-only build requests; URL generation now supports
both normal web requests and the native bundler. A configured release bundle
links to the hosted origin without development-preview copy.

## Deployment and remaining validation

See [hosting instructions](../../../HOSTING.md) and
[production environment example](../../../../deploy/production.env.example).
The supplied web and worker entry points validate production settings; `--check`
does not connect to the database or disclose credentials. Production ignores
the local `.env`; public links never use a request's internal backend host.

The Docker build was blocked by local daemon permissions, including after
sandbox escalation. It was not completed locally. CI includes a Docker build
and container configuration check, but that remote workflow has not been run
as part of this session. No public deployment or live SMTP/provider callback
verification is claimed.

Hosting still requires an actual public HTTPS origin, durable database/shared
storage, current ClamAV signatures, web/worker services, and provider-specific
proxy/email configuration. Keep one web replica while IP limits are process
local. Native device validation, personal referral attribution and the deferred
staff MFA work are outside this increment.
