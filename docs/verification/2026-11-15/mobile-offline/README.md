# Native offline workspace — 15 November 2026

Android and iPhone now include the real **Offline & sync** workspace and its
assets in the application bundle. Failed same-site GET navigation or a server
5xx response opens it; cold-start waiting is bounded to eight seconds. Android
uses `loadDataWithBaseURL`; iOS uses the supported iOS 15+
`loadSimulatedRequest(_:responseHTML:)` API. Both load trusted bundled content at
the configured site's origin to retain the existing WebView IndexedDB store.
There is no separate account store or copied session token. Certificate errors,
authorization responses and failed form submissions are not hidden by fallback.

The workspace reuses encrypted saved records, durable non-exportable keys,
explicit drafts, operation receipts, conflict handling and resumable video
staging. Foreground/resume and reconnection trigger synchronization. Identity is
also checked when only unqueued drafts remain, so known session revocation clears
access. The website's ordinary connected and service-worker behavior remains
available; no existing feature or sign-in method was disabled.

## Verification

- **30 passed:** targeted Python tests covering the native bundle, install page,
  offline operations, content, uploads and migration. After the final bundle
  changes, its five focused tests passed again.
- **4 passed:** Node configuration tests, including a release bundle, an
  unconfigured preview, origin validation and absence of a separate error-page
  origin.
- The real bundled document passed the isolated Chrome journey at 320, 390 and
  1280 pixels. The server was stopped, service workers were bypassed, their
  registrations/caches removed and Chrome fully closed/reopened twice.
- The journey verified saved job/profile/draft recovery, offline profile edits
  and post queueing, automatic reconnect, a deliberately lost committed response
  with no duplicate post, logout/account isolation and revocation of a workspace
  containing only an unsent draft. The test produced no unhandled JavaScript
  errors or application-server log errors. See [report.json](report.json).
- Chrome document interception substitutes only for the native document loader.
  Actual browser storage, crypto, the HTTP session/CSRF checks and database writes
  are exercised. This is not a test of Android WebView or WKWebView execution.
- The Android APK compiled and packaged successfully. Its development signature,
  metadata, ZIP integrity and embedded offline document were verified. Android
  and iOS bundles match byte-for-byte. See [artifact.json](artifact.json).
- iOS asset synchronization and property-list parsing passed. Ruff, JavaScript
  syntax and `git diff --check` passed. There was no Xcode build, device/emulator
  installation, remote workflow run or store publication.

Screenshots: [390 pixels](offline-workspace-390.png),
[320 pixels](offline-workspace-320.png),
[1280 pixels](offline-workspace-1280.png).

## Artifact and remaining release work

The local development APK is `mobile/dist/nurse-ng-preview.apk`, package
`com.nurseng.app.preview`, labelled **Nurse.ng Preview**. It replaces the earlier
preview recorded in `../mobile-app/`. It contains an **Open offline workspace**
entry and the full neutral workspace, but no server address or member data.
First sign-in and preparation of member content require a reachable configured
server. Hosting still has to be set up; this is not a public connected release.

Before release, run the same sign-in/save/airplane-mode/force-close/reopen/reconnect
journey on Android and iPhone. Verify the same-origin native loading, device
storage retention/eviction, attachments, interrupted uploads and external-provider
sign-in. iPhone additionally needs a Mac/Xcode and Apple signing/distribution.
Saved snapshots retain the existing 24-hour expiry; drafts expire after seven
days. Clearing app data or uninstalling removes local work. Closed-app background
delivery is not promised.

Setup and commands: [mobile/README.md](../../../../mobile/README.md).
