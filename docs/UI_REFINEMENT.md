# Nurse.ng UI consistency review

9 November 2026. This refinement keeps the existing theme, colours, navigation,
icons and page structures. It uses the existing Jinja templates, plain JavaScript
and CSS layers; no frontend dependency was added.

## Pages inspected and corrections

| Pages | Finding and correction |
| --- | --- |
| Network | Lists were capped at 46rem inside a wider page, leaving unused space. Connections/following and incoming/sent requests now use two bounded columns that stack when space is limited. Section counts and concise guidance explain what appears in each area. The repeated heading actions were removed; one contextual **Find colleagues** action remains when useful. |
| Messages and conversation threads | An account without connections showed two empty columns and repeated discovery links. It now shows one clear explanation and action, without the fixed conversation height. Populated contacts, history and composer retain their structure. |
| Notifications and preferences | A side card repeated the heading’s Preferences link. The feed now uses the available content width. Empty filtered views offer a return to all notifications; the initial empty state explains expected activity. |
| Colleague directory, onboarding and suggestions | Discovery labels now use **Find colleagues** and **Suggested colleagues**. The mixed people/opportunities page is **Suggestions for you**. Empty searches have one Clear filters action; suggestions have one directory action. Spacing between guidance and results is consistent. |
| Dashboard | Removed duplicate job-directory and colleague-directory links within their sections. Improved spacing after the account notice. Section headings and empty descriptions use the shared scale. |
| Jobs, applications and saved opportunities | Shared heading/empty-state typography. Applications explain what is recorded here and show one relevant browse action. Existing useful saved-opportunity guidance and search/filter layouts remain. Job detail/form layouts were also exercised by the quality checks. |
| Community feed, followed views, topics and conversation forms | Colleague terminology is consistent. The initial feed avoids repeating the compose action. Topic/banner and conversation headings follow the common page scale. Reading widths and reply/composer structure remain. |
| Profile, editing, sharing, verification and account settings | Equivalent page and section headings use the shared scale. Existing helpful profile prompts and readable form widths remain. The professional-profile editor retains its original left-aligned fields and copy after visual review. |
| Learning, resources and events | Page headings and relevant section headings follow the shared scale. Resource cards, external links and useful event guidance retain their established layout and purpose. |
| Reels, My reels and upload/status pages | Consistent page headings; clearer empty-state hierarchy. Create actions are not repeated in empty views. Filtered and later-page empty states return to the appropriate feed instead of opening the upload form under an “Explore reels” label. Media layout and playback controls remain. |
| Staff user overview, document review, moderation, recruitment sources and vacancy records | Consistent heading sizes. Review, report and discovery empty states explain what fills their queues. Added separation below recruitment filters so the next link has sufficient clickable space. Analytics, review tables and administration forms retain their different functional widths. |
| Offline & sync | Inherits shared heading typography. Updated stylesheet and feedback-script URLs are versioned with the public shell cache so returning browsers receive the changes. |

## Shared implementation

The existing stylesheet order remains intact: component mechanics in `app.css`,
visual rules in `design.css`, theme/accessibility variables in `appearance.css`,
and feature styles afterward. Competing page-heading size overrides were removed.

| Role | Standard desktop | Narrow screens |
| --- | --- | --- |
| Main page heading | 2rem / 28px | 1.85rem / about 26px |
| Section heading | 1.35rem / about 19px | Same scale |
| Main supporting descriptions and empty-state copy | 1rem / 14px | Same scale |

These values follow the existing 14px root. The larger-text preference continues
to scale them. Card labels, metadata, statistics, dialog headings and the public
landing/authentication marketing panels retain their distinct roles.

`_empty_state.html` provides a reusable title, explanation and optional action.
Compact states use the surrounding section’s surface instead of another filled
box. New Network styles use the existing surface, border, radius and colour tokens.
The page keeps the shared 1,110px maximum width.

Browser verification also exposed a submission bug: controls named `action`
(including Accept and Decline) masked the form’s JavaScript `action` property.
The shared feedback handler now reads the declared HTML attribute. The existing
discovery browser runner covers both responses, including their saved outcomes.
No request fields, server endpoints or business rules changed.

## Verification record

- Before-change screenshots and computed layout measurements cover 25 pages in
  31 states, in `/tmp/nurse-ui-baseline-i_usz0m5/` and
  `/tmp/nurse-ui-baseline-8xpsk8aa/`.
- Final member-page review covers 68 states in
  `/tmp/nurse-ui-refinement-jynbhy02/`: desktop 1440px, tablet 900/1024px,
  mobile 320/390px, dark/light themes, larger text and 200% text. Every measured
  page heading follows the shared scale; none of these states has horizontal
  document overflow. The 39 selected axe A/AA audits report no violations.
- That review exercised empty and populated Network states, keyboard acceptance,
  decline/removal, following/profile navigation, sending a message, directory
  search/reset, filter destinations, mobile navigation and contextual action counts.
- The remaining eight staff states passed at 1440/390px, including recruitment
  after its filter-spacing correction. All eight selected axe audits passed without
  document overflow. The stopped-server check also confirmed that the neutral
  offline shell uses the refined typography from the final version 8 cache:
  `/tmp/nurse-ui-refinement-o9jhcz30/`.
- The existing quality runner passed 23 audited states plus profile submissions,
  community drafts/replies, keyboard dialogs, job validation/duplicate prevention,
  event publishing/RSVPs and 320px reflow with enlarged text:
  `/tmp/nurse-quality-browser-wqg4zzmp/`.
- Discovery’s registration, onboarding, privacy, recommendations, filters,
  pagination, following, connection requests and Accept/Decline checks passed:
  `/tmp/nurse-discovery-browser-cgcecx7c/`.
- Notifications/preferences, incoming messages, complete 128-message history,
  scroll preservation, offline/lost-response retry and access revocation passed:
  `/tmp/nurse-notifications-browser-r0i8ij1i/`. The test now waits for the specific
  incoming message before checking history; an already-visible jump button was
  not sufficient to identify that arrival.
- The tour’s page targets, including the empty Messages layout, passed at
  320/390/1280px when started through Settings. Keyboard containment, pause/resume,
  reload, lost-response recovery, missing targets, display preferences and landscape
  geometry were also checked in `/tmp/nurse-ui-tour-95qgaoms/`. The separate initial
  invitation failure described below prevented the original full tour runner passing
  during this review; it was fixed in the follow-up recorded below.
- The 114 focused Python cases passed across the main run and the corrected
  Reels-copy assertion rerun. Coverage includes community, workspace flows,
  discovery, notifications, feedback, events, Reels and offline rendering.
- Template parsing, JavaScript syntax, Ruff and whitespace checks pass. All 94
  application Python files match their hashes from before this refinement.

All browser accounts and writes use temporary databases and directories. These
are Chrome checks with emulated viewport sizes, not physical-device or Safari
acceptance tests. Automated accessibility results do not replace assistive
technology testing.

## Deliberate exceptions

- Readable form/profile widths, conversation reading measures, the vertical Reels
  viewer and the wider analytics workspace remain purpose-specific.
- The professional-profile editor keeps its original left alignment. The temporary
  centered treatment was removed following the user's visual review; the template
  matches its pre-refinement copy. The design stylesheet and shell cache now use
  version 8 so returning browsers receive the restored layout.
- Landing-page and authentication marketing typography remains distinct from
  ordinary application page headings. Labels and metadata were not resized en masse.
- Sidebar access remains available alongside an occasional useful empty-state
  action. Repetition within a page heading and the same empty state was removed.
- Already-helpful saved-job, profile, resource and event states retain their copy
  and actions, benefiting from shared typography where applicable.
- The first-sign-in tour invitation was not visible in the original browser run
  (`/tmp/nurse-tour-browser-zm70hwr0/`), and the same issue recurred for a new role
  in the Settings-entry variant. This required a separate review of server navigation
  and invitation handling. Starting the tour through Settings works against the
  updated page targets. Invitation and authentication rules remain unchanged under
  the requested frontend-only scope. The subsequent fix is recorded below.

The temporary visual audit can be repeated with
`venv/bin/python /tmp/nurse-ui-verify.py`. The repository browser runners are
`tests/browser/quality.py`, `tests/browser/member_discovery.py` and
`tests/browser/notifications.py`.

## First-sign-in invitation follow-up — 9 November 2026

The invitation issue is resolved. The offline worker's timeout-enabled fetch changed
navigation metadata to `same-origin/empty`, so the renderer treated the welcome
page as a background request. The v9 worker now marks top-level navigations and the
renderer recognizes that marker with matching same-origin metadata. Background
requests and prefetches still cannot show or consume an invitation.

The complete original tour browser journey passed for nurse, employer, partner and
staff accounts, including first invitations, all steps at 320/390/1280px, repeat
sign-in, keyboard containment, restart, skip/pause/resume, lost responses, stale
tabs and unavailable targets. Artifacts: `/tmp/nurse-tour-browser-bbt7ansm/`
(32 screenshots). The invitation screenshot was visually reviewed. The focused
delayed-save run also passed in `/tmp/nurse-tour-browser-dxmxsusi/`. All 31 tour
backend and migration tests passed; additional regression results are in the
[work log](WORK_LOG.md).
