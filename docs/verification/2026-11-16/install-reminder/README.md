# Persistent installation reminder dismissal

The member reported that the “Nurse.ng, wherever you go” card remained on every
page. It had no dismiss action, and installation acceptance/completion was held
only in the current document's memory.

Added an accessible 44-pixel close button and a browser-local reminder preference.
Closing it, accepting/cancelling the installation prompt, or opening installation
help from the card suppresses reminders across navigation/reloads and later
visits. Installed standalone/native contexts also remember suppression. Settings
and the explicit `/app` installation page remain usable. Other open tabs receive
the normal browser storage event. Storage failure falls back to session storage
or, if both stores are unavailable, dismissal for the current page.

CSS, script and service-worker asset versions were advanced so installed/cached
clients receive the new control on refresh/navigation.

- `pytest.xml`: **9 installation-page checks passed**, 4.36 seconds.
- `browser.json`: final isolated Chrome journey passed at 320, 390 and 1280
  pixels. Checks cover keyboard dismissal/focus, navigation/reload persistence,
  accepted install suppression, iPhone help-link suppression, unavailable storage,
  explicit installation, errors/cancellation and overlapping clicks.
- `card-320.png`: the close control and layout at 320 pixels.
- `dismissed-settings.png`: reminder absent while manual installation remains
  available from Settings.

Chrome's real manifest/installability checks passed and a real install offer was
available. OS choices and native/iOS standalone detection were simulated; this
does not claim physical-device installation. Temporary artifacts:
`/tmp/nurse-mobile-app-browser-dl5j9k_s/`. No real account changes, email, deployment
or schema migration occurred. Changes remain local and uncommitted.
