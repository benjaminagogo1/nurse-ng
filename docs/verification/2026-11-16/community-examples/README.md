# Communities members can shape — 16 November 2026

Members can start from six editable examples or create a community with their
own name and purpose. The directory and creation form display examples for
critical care, new-nurse support, local networks, exam preparation, school/alumni
and research. Selecting an example only fills the form; it creates no community
or membership. The optional interest category does not restrict a group's purpose.

Creation links are visible from the feed, composer and onboarding. The account
alias is labelled “Your public display name” to distinguish it from the group
name. Fresh generic posts require a community choice; explicit community links
and restored drafts retain the member's selection.

## Verification

- [Python receipt](python-results.json): **92 checks passed** across community
  growth, existing community behavior, discussions and member discovery.
  Includes editing examples, arbitrary member-created communities, host and
  membership assignment, posting, GET requests with no community writes and
  blank versus explicit community selection.
- [Focused browser results](community-browser/results.json): creation by an
  ordinary member, editable example/blank starting point, posting into the
  chosen group, draft restoration and discard passed. The completed
  [320px](community-browser/320/results.json) and
  [1280px](community-browser/1280/results.json) runs retain their receipts.
- [Accessibility/reflow audits](community-browser/audits.json): **18 page states**
  passed across 390px/light, 320px/dark with 32px root text, and 1280px/light.
  Each width covered the directory, blank form, example form, feed, composer
  and onboarding. Zero selected WCAG axe violations or horizontal overflow.
  Incomplete/manual axe findings are retained; these automated checks do not
  establish complete assistive-technology or physical-device verification.
- [Full draft browser receipt](draft-results.json): restore, validation, offline
  submission, history, tab/discussion isolation, discard, expiry, blocked
  storage, logout, account switching and phone/desktop reflow passed.
- [Local HTTP receipt](local-page.json): the running local directory returned
  200 and displayed the example section and updated stylesheet.
- Ruff, five edited Python files, all 85 templates, service-worker JavaScript
  syntax and whitespace checks passed. Final community CSS is v3 and the
  service-worker shell cache is v33.

Initial browser runs exposed two fixture issues: reading an expired ORM object
after closing its session, and measuring contrast during a theme transition.
The draft fixture now saves the community ID inside the session. Audits load
the member's saved theme before navigation and wait for layout. Longer browser
processes were interrupted; six completed 390px states were retained, followed
by successful separate 320px and 1280px runs. No interrupted whole run is counted
as a completed journey. The previously completed wider engagement regression
was not repeated for this focused change.

The retained [focused runner](focused-browser.py) was generated from the full
community browser runner with unrelated answer/invitation/activity journeys
omitted. Run each viewport separately:

```sh
venv/bin/python docs/verification/2026-11-16/community-examples/focused-browser.py --width=390
venv/bin/python docs/verification/2026-11-16/community-examples/focused-browser.py --width=320
venv/bin/python docs/verification/2026-11-16/community-examples/focused-browser.py --width=1280
```

It uses isolated databases, disabled mail, temporary Chrome profiles and the
same local Chrome/axe prerequisites as `tests/browser/community_growth.py`.
No test accounts, examples or contributions were inserted into the live app.
No new migration, deployment, commit or push was needed.

Inspected screenshots:

- [390px examples](community-browser/390/community-examples-390-light.png)
- [320px enlarged-text examples](community-browser/320/community-examples-320-dark.png)
- [1280px example form](community-browser/1280/community-example-form-1280-light.png)
- [320px restored composer](draft-browser/draft-composer-320.png)
