# Android and iPhone preparation — 15 November 2026

This is the earlier preparation receipt. The local APK has since been replaced
by the [native offline workspace build](../mobile-offline/README.md); its updated
digest and verification are recorded there.

Signed-in website users now see **Install the app**, opening `/app`. Account
settings also links there. The page supports real Android and iPhone download
URLs and explains when a release is being prepared. Existing website features
and sign-in options remain available. No worker service was disabled for this
work, and no deployment or store publication was performed.

## Android artifact

`npm run android:preview` completed successfully using Java 21, Android SDK 36,
Gradle 8.14.3 and Capacitor 8.6.2. The build produced
`mobile/dist/nurse-ng-preview.apk` (4,122,802 bytes). This ignored local build
product is not included in source control.

- Package: `com.nurseng.app.preview`
- Label: **Nurse.ng Preview**
- Version: `0.1.0-preview`; Android 7/API 24 minimum; target API 36
- Android development signature verified using APK Signature Scheme v2
- SHA-256: `cca88ceae1a7f1f2ea9ae2137302ffab4461269ba4d4d5e2b1ec5a69f88ea690`

APK ZIP integrity, application metadata and bundled configuration were checked.
There is no server URL in this artifact. Its bundled screen explicitly says it
is a development preview that cannot sign in or load opportunities. Installation
and execution on a physical Android device or emulator have not been tested.
This is not a functional public release. See [artifact.json](artifact.json).

## Verification

- **54 passed:** `venv/bin/python -m pytest tests/test_mobile_app.py
  tests/test_offline.py tests/test_configuration.py --tb=short`.
- Native configuration suite passed with `npm test` in `mobile/`.
- Browser journey passed at 320, 390 and 1280 pixels: anonymous/signed-in entry,
  download page, settings navigation, large-text dark display, and no JavaScript
  or server errors. Native suppression used a simulated Capacitor API, not a
  real native device. [Browser report](report.json).
- Ruff, changed-template parsing, iOS property-list parsing and
  `git diff --check` passed. Earlier full-suite results from recruitment work do
  not cover these mobile changes.

Selected browser screenshots:
[signed-in entry](install-entry-320.png),
[downloads](download-page-390.png),
[large text and dark display](download-large-text-dark-320.png).

## What remains for public downloads

Host the existing Nurse.ng server over HTTPS, configure its origin in the native
projects, and test the complete app on real devices. Android needs a permanent
release signing key; iPhone needs macOS/Xcode and Apple signing and distribution
credentials. The iOS project is generated but has not been built with Xcode,
signed or installed on an iPhone. The manual GitHub build workflow was not run.

Check external-provider sign-in on devices; Google/LinkedIn may require a
system-browser callback and session handoff. No provider was switched off.
Once signed releases exist, configure their actual download URLs on the website.
Detailed commands are in [mobile/README.md](../../../../mobile/README.md).
