# Nurse.ng for Android and iPhone

These are native installable projects, built with Capacitor 8.6.2, using the
existing Nurse.ng screens and server workflows. They do not replace or remove
website features. Android supports Android 7/API 24 and later; iPhone supports
iOS 15 and later. Application ID: `com.nurseng.app`, version `0.1.0`.

The server is currently local only. Without a configured site, builds open a
clearly labelled **development preview**, not a working public Nurse.ng service.
No production website address, Apple account or public store listing is assumed.
The Android preview uses `com.nurseng.app.preview`, separate from the release app.

## Development

Requires Node 22+, Python 3.12+ with the application's dependencies, Java 21,
Android SDK 36 and the Gradle-selected build tools, and (for iPhone)
macOS with Xcode and Swift Package Manager. The generated platform projects and
Gradle wrapper are included in the source tree; build products, signing keys and local connection
settings are ignored.

The build uses the repository's `venv/bin/python` when present. Otherwise install
the root Python project in a build environment (`python -m pip install .` from
the repository root) and set `NURSE_NG_BUILD_PYTHON` to that interpreter if it is
not `python3`. Python renders the existing neutral offline workspace into the
native bundle; it is not shipped as an on-device server.

```sh
cd mobile
npm ci
npm test
npm run sync
npm run android:preview
```

The APK is written to `mobile/dist/nurse-ng-preview.apk`. It is signed with the
Android development key and is **not a public release**. On this workstation,
Java and the Android SDK are isolated under `.local-tools/mobile/`; the build
script also accepts ordinary `JAVA_HOME` and `ANDROID_HOME` installations.

To test against an Android emulator with the existing local server:

```sh
NURSE_NG_MOBILE_URL=http://10.0.2.2:8000 npm run android:preview
```

The server must allow the requested host. For a physical phone, configure a
reachable development address and the server's host/bind settings yourself;
`127.0.0.1` on a phone refers to the phone, not this computer. The setup does
not expose the local database or server on a network automatically.

Once a public HTTPS site is available:

```sh
NURSE_NG_MOBILE_URL=https://your-hosted-site.example npm run sync
```

Supply the actual origin, with no path or credentials. All authenticated pages
continue to use the server's session and authorization rules. External vacancy
and other third-party links open outside the app. Android Back follows page
history, and iPhone supports back/forward swipe navigation. Connection failures
open the bundled offline workspace described below.

## Offline access

Both native hosts include the actual **Offline & sync** workspace, its styles,
fonts, icons and storage/sync scripts. It opens on a failed same-site GET or a
server 5xx response. A cold start waits at most eight seconds before opening it.
The workspace can start without a previously installed service worker or cached
website document. Certificate failures, authorization responses and failed POST
submissions are not replaced with offline navigation.

After signing in and preparing content in the app while connected, members can:

- Read and search saved opportunities and profile details.
- Reopen and edit explicitly saved message, application, post/reply and Reel
  drafts, including previously saved video chunks.
- Queue supported profile, bookmark and contribution changes for synchronization.
- Reopen the app without internet and recover the same workspace. Reconnection
  and foreground/resume trigger synchronization; confirmed receipts prevent
  duplicate writes after a lost response.

Android loads the bundled document with `loadDataWithBaseURL`, and iOS uses
the iOS 15+ `loadSimulatedRequest(_:responseHTML:)` API, at the configured site's
origin. Both keep the same
WebView data store used while connected. There is no second account store,
offline login or copied authentication token. The existing encrypted IndexedDB
records, non-exportable keys, expiry, consent and conflict handling are reused.
Sign-out/account changes clear access; the neutral shell checks identity on
reconnect even when only unqueued drafts remain.

First sign-in, fresh content, delivery, uploads, account/security changes and
external destinations still need the server. Previously saved snapshots expire
after 24 hours; explicit drafts last up to seven days. Clearing app data or
uninstalling removes local work. Closed-app background delivery is not promised.
See [the full offline behavior](../docs/OFFLINE.md).

An unconfigured preview lets you open the offline workspace but contains no
member data. Configure a reachable development/hosted origin and sign in in the
app to prepare a workspace; the phone does not share browser or desktop data.
Use HTTPS for offline device tests: ordinary LAN HTTP lacks the required secure
storage context (Android emulator loopback alone does not establish it).

Verification here covers the actual bundled document in Chrome with the server
stopped, all service-worker caches removed, full browser restarts, queued edits,
reconnection, duplicate prevention and account isolation. The Android project
builds, but native WebView execution/storage and iPhone cold starts still need
device validation. No Xcode build or signed iPhone release is claimed.

## Android release

Keep a permanent signing key in private storage and back it up. Supply these
through the build environment; do not commit them:

- `NURSE_NG_MOBILE_URL`: actual public HTTPS origin.
- `NURSE_NG_KEYSTORE_PATH`: absolute path to the release keystore.
- `NURSE_NG_KEYSTORE_PASSWORD`, `NURSE_NG_KEY_ALIAS`, `NURSE_NG_KEY_PASSWORD`.

Then run `npm run android:release`. The output is `mobile/dist/nurse-ng.apk`.
The release command requires an explicitly configured HTTPS site and signing
credentials; it cannot accidentally publish the unconfigured preview. Upload
the signed APK to the site's download hosting, or build an Android App Bundle
for a Google Play release using the same signing configuration.

## iPhone release

On a Mac, set `NURSE_NG_MOBILE_URL` to the real HTTPS origin, run
`npm run ios:release`, then `npm run open:ios`. The release setup turns off native
WebView debugging; use `npm run sync` only for development previews.
Choose your Apple development team in Xcode, archive for an iOS device and
distribute with TestFlight or the App Store. Signing/provisioning and Apple
review are separate from generating the project. An unsigned simulator build
cannot be installed on somebody's iPhone.

The manual `Mobile preview builds` GitHub workflow prepares Android preview and
unsigned iOS **simulator** artifacts. It has not been run remotely as part of
this setup. It does not publish store releases or require signing secrets.

Before public release, check sign-in, navigation, file/video uploads, offline
recovery and background/resume on real devices against the hosted server.
Google/LinkedIn sign-in may need provider-approved system-browser callbacks and
native session handoff; embedded-browser approval is not implied by a web login.
No existing website sign-in method is switched off by the mobile setup.

## Website install entry

Signed-in website users see **Install the app**. When Chrome or Edge offers
browser installation, clicking it opens that prompt directly. Otherwise it opens
`/app`, where both the Android and iPhone panels reveal working installation
instructions. The entry is hidden in a native host or standalone app. Account
settings also links to the app page.

The reminder has a close button. Dismissal is saved in this browser, so it stays
hidden across pages and later visits. Starting installation, cancelling an OS
prompt, or opening installation help from the reminder also suppresses further
reminders. Settings and `/app` remain available for manual installation. If local
storage is unavailable, the preference falls back to session storage; if both
are blocked, dismissal still works for the current page.

Android uses Chrome's install prompt or its **Install app / Add to Home screen**
menu. iPhone/iPad uses Safari's **Share → Add to Home Screen** flow; websites
cannot trigger that iOS confirmation directly. Desktop steps cover Chrome and
Edge. Dismissed or failed prompts show menu instructions, and repeated clicks
cannot reuse a consumed prompt. The web manifest keeps a stable identity and
includes 192/512-pixel PNG icons; Apple uses the 180-pixel touch icon.

Browser installation uses the existing website and offline storage/synchronization
flows. Sign in in the installed app while connected, then prepare saved offline
content there: devices and browsers do not necessarily share local storage.
Phone installation needs a reachable HTTPS site. Localhost works for a browser
on this computer; ordinary LAN HTTP does not satisfy browser installation and
offline storage requirements.

After releases exist, set these on the server:

```dotenv
NURSE_NG_ANDROID_APP_DOWNLOAD_URL=https://your-hosted-site.example/downloads/nurse-ng.apk
NURSE_NG_IOS_APP_DOWNLOAD_URL=https://apps.apple.com/app/your-real-app-id
```

TestFlight links and same-site download paths are also supported. These optional
native downloads appear only when configured; missing releases do not disable
browser installation. The disconnected preview APK is not advertised as a
working download. Native signing, hosting and store distribution remain separate
from installing the web app.

## Branding and checks

Icons derive from the existing Nurse.ng SVG, not a new identity. Regenerate the
native PNG sizes using `venv/bin/python mobile/scripts/generate-icons.py` from
the repository root; Pillow is already an app dependency.

Focused server checks: `venv/bin/python -m pytest tests/test_mobile_app.py
tests/test_offline.py tests/test_configuration.py`. Browser checks:
`venv/bin/python tests/browser/mobile_app.py`.
The bundled offline journey is `venv/bin/python tests/browser/mobile_offline.py`;
it uses isolated accounts/data and simulates only the native document loader.
