# Understanding the frontend

Nurse.ng renders Jinja HTML on the server, then adds small feature scripts. The
mobile projects wrap this hosted experience with Capacitor and a bundled neutral
offline workspace. There is no separate React/Vue application or on-device Python
server. The [frontend reference](reference/FRONTEND.md) indexes every authored
template, browser script and stylesheet.

## Page composition and context

`app/web/templating.py` owns common rendering. It supplies `csrf_token`, navigation
section, feedback, private draft scope, unread counts and server tour state. It
returns `Cache-Control: no-store` and records only eligible successful signed-in
page navigation as activity. Enhanced form failures may return feedback JSON
instead of HTML; inspect both paths when changing error rendering.

`app/templates/base.html` supplies the document head, signed-in navigation/shell,
display/feedback/tour components and shared assets. Most pages replace `content`
and optionally `extra_head` or `scripts`. Education extends its own `base.html`
and exposes `education_content`/`education_scripts`; Reel pages use `layout.html`.
Files beginning with `_` are reusable partials/macros rather than standalone pages.

Routes construct domain-specific context. A missing context key should be fixed
in the owning context builder rather than guessed from another member's record.
Jinja conditions shape presentation; service authorization remains authoritative.
Use escaped template values and `textContent`/DOM APIs for member text. Server JSON
embedded in a page uses Jinja's JSON serialization rather than string concatenation.

Use Jinja comments for maintainer notes; ordinary HTML comments become public
page source. Shared icons live in `_icons.html`, and repeated display, avatar, like,
feedback, post-card and pagination mechanics should reuse existing components.

## Script and style order

`display.js` runs synchronously before stylesheets so saved theme/accessibility
preferences apply before first paint. The base layout loads shared CSS in this
order: `app.css` (mechanics), `design.css` (visual refinements/fonts), then
`appearance.css` (theme/accessibility tokens), followed by feature CSS. Consequently,
later feature rules must use theme variables rather than assume a white surface.
Education/Reel-specific styles load through their layouts after the shared head.

Deferred offline scripts retain their ordered dependency chain:

```text
time-display.js
offline-store.js -> offline.js -> offline-sync.js
                             -> offline-data.js -> offline-content.js -> offline-upload.js
```

All deferred scripts execute after parsing, in document order. `offline.js` needs
`NurseOfflineStore`; later scripts extend/use `NurseOffline`. Moving them to `async`
or loading an extension before its base can break cold-start recovery. Shared
navigation/feedback/like/community scripts initialize against their own DOM hooks.
Account-only polling/tour/activity scripts load only for a signed-in page. Feature
scripts commonly return early when their root does not exist; keep that property.

`service-worker.js` has an explicit shell/asset cache version and asset list.
Changing asset URLs or script contracts may require updating the cached list and
cache version, plus regenerating the mobile neutral bundle. Do not add signed-in
documents, message/evidence files or provider tokens to the service-worker cache.
Ordinary stylesheet comments alone do not require changing public cache identities.

## Browser contracts

| Owner | Main hook/global | Responsibility |
| --- | --- | --- |
| `app.js` | Navigation dialog, `.nav-toggle`, password/file controls | Shared keyboard/focus/navigation mechanics |
| `display.js` | Root `data-theme`, `data-text-size`, `data-contrast`, `data-motion` | Browser-local theme/accessibility choices |
| `feedback.js` | `data-feedback-form` | Preserve submitter/form values, pending status and server feedback |
| `community-drafts.js` | Draft controls and server `published-draft` acknowledgement | Recover the right explicit draft and discard only confirmed versions |
| `community-replies.js` | `data-reply-context-base`, `in_reply_to_id` | Selected reply excerpt, permalink and stale-fetch cancellation |
| `community-growth.js` | `data-share-url`, `data-community-post-kind` | Native/copy sharing fallbacks and activity-specific fields |
| `likes.js` | Shared like form and `data-like-count` | Desired-state submission and server count reconciliation |
| `messages.js` | `data-conversation`, message IDs and send form | Authorized live updates, deduplication, read receipts and file progress |
| `notifications.js` | Inbox/bell/count hooks | Visible-page refresh and server-confirmed read actions |
| `activity.js`, `analytics.js` | Activity CSRF meta, `data-analytics-page` | Bounded meaningful activity and authorized staff charts |
| `mobile-app.js` | Browser install event/reminder/help controls | Installation UI and browser-local suppression of repeated reminders |
| `tour.js` | `tour-config`, `guided-tour` | Server-defined role-aware destinations and saved transitions |
| `reels.js` | `data-reels-viewer`, `data-reel-upload` | Active video, sound/captions, queued upload status and explicit drafts |
| `education.js` | `.edu-page`, authoring/schedule/confirmation hooks | Learning form enhancement; no learner answer-key/draft storage |
| `education-room.js` | Authorized room configuration | LiveKit media, host controls, live state and media/timer cleanup |
| `time-display.js` | `window.NurseTime` | Shared UTC timestamp display |
| `offline-store.js` | `window.NurseOfflineStore` | Encryption, ownership, expiry and cross-tab coordination |
| `offline.js` and extensions | `window.NurseOffline` | Verified identity, snapshots, drafts, queued changes and reconnect sync |
| `home-carousel.js` | `data-home-carousel`, hero slide/control hooks | Anonymous landing carousel; visibility/motion/focus stop automatic changes |

`data-*` selectors form the interface between templates and scripts. Rename both
sides together. Input `name` attributes and clicked submit-button name/value pairs
are also contracts: the next-step hide button must submit `dismiss=yes`, while
ordinary saving deliberately clears dismissal. [Dashboard onboarding](DASHBOARD_ONBOARDING.md)
explains the rule.

## Local events

| Event | Purpose / main participants |
| --- | --- |
| `community:reply-context` | Tell reply/draft/activity controls that the selected response context changed. |
| `nurse:messages-read` | Notify inbox/badge listeners after incoming message receipts are saved. |
| `nurse:analytics-updated` | Refresh controls after staff analytics content changes. |
| `nurse:offline-change` | Announce changed encrypted offline storage state. |
| `nurse:operation-confirmed` | Reconcile a confirmed operation across offline participants/tabs. |
| `nurse:offline-draft-saved` | Signal explicit local draft persistence on its form. |
| `nurse:offline-confirmed` / `nurse:offline-published` | Reconcile a saved contribution after actual server confirmation. |
| `nurse:sync-request` | Request an eligible sync pass, including native foreground/resume. |

Event dispatch alone never establishes server delivery, login, publication,
attendance or permissions. Use the confirmed response/receipt behind the event.

## Browser state and privacy

Display preferences and install-reminder dismissal are browser-local. Journey
dismissal and tour progress are database/account-owned and follow the account to
another device. The browser must not infer that one choice completes another.

The offline store requires explicit preparation/consent, encrypts private records
with non-exportable browser keys, binds records to the active account scope and
expires snapshots/drafts. It coordinates concurrent tabs and invalidates access
after sign-out/account changes. Clearing app/browser storage can remove local work;
there is no offline first-time login. See [offline architecture](OFFLINE_ARCHITECTURE.md)
for supported operations, TTLs, quota/fencing and receipt behavior.

Authentication errors must not be disguised as a disconnected workspace. A failed
POST is not safely replayed unless it uses the supported idempotent operation
protocol. A thumbnail or uploaded file cannot be considered public until server
publication checks succeed. Browser state is a usability layer, not authority.

## Native integration

`mobile/scripts/configure.mjs` validates the target origin and calls
`bundle-offline.py` to render/package neutral HTML and public assets. It writes
generated Capacitor configuration/bundles; do not hand-edit build output.

Android `MainActivity` installs `OfflineWebViewClient`, handles Back/resume, and
requests sync. iOS `SceneDelegate` creates the Capacitor view and forwards existing
navigation policies while adding fallback. Both keep the hosted origin and the
same WebView data store when opening the bundled workspace. They do not copy
account cookies/keys/data into an APK or iOS bundle.

Cold-start/network failures use bounded same-site GET recovery. Certificate failures,
authorization errors and failed POSTs retain their original meaning. The native
hosts cannot grant permissions absent from the server. See [mobile setup](../mobile/README.md)
for Java/SDK/Xcode requirements, release signing and real-device verification limits.

## Verify frontend changes

Check narrow/wide layouts, keyboard focus, screen-reader labels, reduced motion,
dark/high-contrast themes and enlarged text where the changed component uses them.
Ordinary forms should retain a useful server-rendered path when enhancement fails;
live media and encrypted offline functionality inherently require their scripts.

Use the owning browser runner from [tests](../tests/README.md); those runners create
isolated accounts/storage and report artifacts. Browser simulation of a neutral
native shell is not a real Android/iPhone WebView check. Do not replace that release
evidence with a local browser screenshot.
