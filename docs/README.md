# Nurse.ng documentation

Start with the [code guide](CODE_GUIDE.md). It explains the application, domain
boundaries and how to trace a feature without reading the whole repository.

## Current maintainer guides

| Need | Read |
| --- | --- |
| Architecture, feature owners and request lifecycle | [Code guide](CODE_GUIDE.md) |
| Every Python module, function/class and declared route | [Backend reference](reference/BACKEND.md) and [route reference](reference/ROUTES.md) |
| Every table, mapped field, relationship and constraint | [Data guide](DATA_GUIDE.md) and [schema reference](reference/SCHEMA.md) |
| Templates, CSS, scripts, storage and UI events | [Frontend guide](FRONTEND_GUIDE.md) and [frontend reference](reference/FRONTEND.md) |
| Configuration names, defaults and validation | [Configuration reference](reference/CONFIGURATION.md) |
| Run, change, debug and hand over the application | [Maintenance guide](MAINTENANCE.md) |
| Dashboard next-step reminder behavior | [Dashboard onboarding](DASHBOARD_ONBOARDING.md) |
| Test grouping, fixtures and browser/hosting runners | [Tests guide](../tests/README.md) and [test reference](reference/TESTS.md) |
| Migration graph and upgrade rules | [Migration guide](../migrations/README.md) |
| Startup/container/CI/mobile code | [Infrastructure reference](reference/INFRASTRUCTURE.md), [deployment guide](../deploy/README.md), [hosting](HOSTING.md) and [mobile guide](../mobile/README.md) |
| Refresh the generated code reference | [Documentation tools](../tools/README.md) |

The reference pages are generated from checked-in source without importing the
application or connecting to a database. They are navigation aids; explicit
service checks and feature guides establish permissions and lifecycle semantics.

## Feature and operations guides

| Domain | Guides |
| --- | --- |
| Accounts and sign-in | [Account management](ACCOUNT_MANAGEMENT.md), [social sign-in](SOCIAL_SIGN_IN.md) |
| Profiles and discovery | [Member discovery](MEMBER_DISCOVERY.md), [community expansion](COMMUNITY_EXPANSION.md) |
| Community participation | [Community engagement](COMMUNITY_ENGAGEMENT.md), [peer support, series, invitations and digest](COMMUNITY_PARTICIPATION.md), [sharing/discovery expansion](COMMUNITY_EXPANSION.md) |
| Learning and events | [Live learning architecture](LIVE_LEARNING_ARCHITECTURE.md), [events](EVENTS.md) |
| Conversations and notifications | [Private message files](PRIVATE_MESSAGE_FILES.md), [notifications](NOTIFICATIONS.md) |
| Reels and moderation | [Reels](REELS.md), [engagement and admin](ENGAGEMENT_AND_ADMIN.md) |
| Jobs and recruitment | [Nigerian opportunities](NIGERIAN_OPPORTUNITIES.md), [source operations](RECRUITMENT_SOURCE_OPERATIONS.md), [search discovery](SEARCH_DISCOVERY.md), [automatic discovery](AUTOMATED_RECRUITMENT_SOURCE_DISCOVERY.md) |
| Employer approval and document review | [Employer/evidence operations](EMPLOYER_AND_EVIDENCE_OPERATIONS.md) |
| Offline/mobile | [Offline behavior](OFFLINE.md), [offline architecture](OFFLINE_ARCHITECTURE.md), [mobile](../mobile/README.md) |
| Tour, analytics and quality | [Onboarding tour](ONBOARDING_TOUR.md), [member analytics](MEMBER_ANALYTICS.md), [quality verification](QUALITY_VERIFICATION.md) |
| Deployment and processes | [Hosting](HOSTING.md), [worker operations](WORKER_OPERATIONS.md), [local operations](LOCAL_OPERATIONS.md) |

## Historical material

`verification/`, dated assessments, build plans, proposals and `WORK_LOG.md` record
earlier decisions or checks. A test count, schema revision or deployment statement
in one of those documents describes that point in time. Determine today's schema
with `alembic heads` and today's behavior from current source/tests. Proposals
describe possible work, not features that are necessarily implemented.

[DECISIONS.md](DECISIONS.md) records design rationale. Update a current guide when
a contract changes, and add dated verification evidence when a release is checked.
See [documentation conventions](DOCUMENTATION.md) for ownership and refresh rules.
