# Centered notices and consistent page spacing

Implemented the requested clean, centered notice boxes and a shared **20px
page gutter**. Transparent page wrappers apply that gutter once. Boxed forms
retain their inner padding and centered maximum widths. Headers and footers
use the same gutter, including mobile layouts.

Feedback, tour invitations and installation reminders are centered and bounded
to 480px; compact feedback is bounded to 400px. Legacy form/Reels notices and
floating toasts are constrained, and native display/Reels dialogs retain at
least 20px side clearance. Status/error semantics, field validation, keyboard
focus and 44px close controls remain available.

The first enlarged-text feedback check reproduced a hidden-heading problem:
the header grew from 65px to about 100px, while the focused notice stayed at
81px. The feedback script now keeps a focused notice visible when the header,
panel or viewport resizes. It leaves focus and scrolling alone while the user
works in a form. The successful repeat measured the notice at 114px beneath
the 100px header, with 20px side gutters and fully visible copy.

## Verification

- **13 related Python checks passed**, covering feedback and installation page
  behavior (`tests/test_quality_feedback.py` and `tests/test_mobile_app.py`).
- The existing account-feedback journey completed all assertions at
  **320/390/1280px**, including enlarged text, pending/error/success notices,
  keyboard focus, dismissal, offline/lost responses and account actions.
  Body text contrast measured **5.81:1 light** and **8.40:1 dark**.
- The existing quality journey completed **25 audited page states**, covering
  jobs, profile editing/sharing/verification, settings, notifications, messages,
  community, events and staff/recruitment forms. All reported a 20px main gutter;
  there were no axe violations or horizontal overflow. The 320px checks use
  enlarged 32px base text. Navigation also checked native dialog keyboard focus.
- The existing installation journey completed all assertions at
  **320/390/1280px**, including keyboard dismissal, reload/navigation persistence,
  blocked storage, prompt outcomes and Android/iPhone help. Its final screenshots
  include the installation card's improved mobile text layout.
- The existing tour `--loading-only` journey passed the first invitation,
  keyboard focus, delayed/repeated input, pause during save and resume. This
  focused run does not claim to repeat every tour step or physical device check.
- Final service-worker/feedback-script syntax, template parsing and whitespace
  checks passed. Asset/cache versions were advanced to deliver the updated CSS
  and script to installed browsers.

The temporary diagnostic runner executes the existing browser journeys with
measurement/progress output; their assertions are retained. The repository
browser fixtures were not changed for this layout task. Two initial wider runs
ended with SIGTERM and are not counted as passes. One initial installation run
timed out at sign-in; the isolated diagnostic repeat completed all its checks.
The initial enlarged-text feedback failure is counted only as a reproduced and
corrected issue, not as a passing run.

## Evidence

- [Feedback receipt](feedback-browser.json) and
  [notice measurements](feedback-geometry.json).
- [25-state receipt](wide-browser.json), [axe/reflow audits](wide-audits.json) and
  [page-gutter measurements](page-layout.json).
- [Installation receipt](mobile-browser.json) and [tour receipt](tour-browser.json).
- Screenshots cover light/dark feedback, enlarged text at 320px, desktop feedback,
  the tour invitation, jobs/events and the final installation card/page.

The 25-state/account screenshots preceded the final installation-card-only
mobile text adjustment. The final installation journey checked that adjustment;
the shared page/feedback styles and behavior stayed the same.

All journeys use isolated local accounts/databases and disabled or file-only mail.
No real mail, deployment or live schema migration was performed. Changes remain
local and uncommitted.
