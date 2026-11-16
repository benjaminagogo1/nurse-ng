# Installation repair — 16 November 2026

The member reported that **Install the app** opened Android/iPhone panels with
nothing to click. Both native download settings were empty; the page only
rendered release placeholders. Chrome's [baseline inspection](before.json)
already found the site installable, but found zero install controls/downloads.
The original script only hid the member banner in native hosts.

## Completed behavior

- The Android and iPhone panels now contain clickable installation steps.
  Android uses an available Chrome install prompt or its browser menu. iPhone
  uses Safari's **Share → Add to Home Screen** flow.
- Eligible Chrome/Edge sessions show **Install Nurse.ng**. The existing member
  banner invokes the offered browser prompt directly, retaining `/app` as the
  fallback when no prompt is available.
- Prompt dismissal/failure reveals useful menu instructions. A consumed prompt
  cannot be reused; overlapping clicks do not open multiple prompts. Installed
  standalone/native sessions suppress further installation offers.
- Added the existing brand's 192/512-pixel PNG manifest icons and 180-pixel Apple
  touch icon, kept a stable manifest identity, and advanced the public offline
  shell cache so browsers receive the updated script/style/assets.
- Configured native downloads remain available. Missing releases no longer
  leave the page without an action. The disconnected preview APK is not offered
  as a working public release.

## Evidence

- [Python regression](pytest.xml): **60 passed**, covering installation pages,
  icon responses/manifest identity, configuration, offline authorization/sync
  and native offline bundling. Current Ruff, JS syntax and whitespace checks pass.
- [Isolated browser journey](browser.json): passed at 320, 390 and 1280 pixels,
  including large text/dark layout, both device disclosures, Android/iPhone user
  agent emulation, the banner action and installed-state suppression.
  Chrome reported zero installability errors and offered its real install event.
  Acceptance, dismissal, failed prompts and overlapping clicks used simulated
  prompt choices; native/iOS standalone flags were also simulated.
- [Running local site](live.json): the install button was present and ready,
  both device actions were present, and Chrome reported zero manifest or
  installability errors at `http://127.0.0.1:8000/app`.
- Screenshots inspected: [desktop](desktop.png), [phone](phone.png),
  [Android steps](android.png) and [iPhone steps](iphone.png).

No physical phone installation or Safari execution is claimed. A phone needs a
reachable HTTPS site; localhost only refers to the device running that browser.
Native APK/store distribution still requires hosting and signing as documented
in [the mobile guide](../../../../mobile/README.md). No deployment, account-data
change or schema migration was performed. Changes remain local and uncommitted.
