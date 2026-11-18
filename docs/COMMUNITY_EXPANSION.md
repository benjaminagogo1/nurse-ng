# Community expansion

## Current product direction — clarified 17 November 2026

Nurse.ng's immediate goal is increased market penetration, high adoption and
sustained participation in an inclusive nursing community. The audience begins
with a student's first day in nursing school and extends through newly qualified
and experienced nurses, specialists, leaders, researchers, nursing educators
and professors of nursing. Members at every stage should find a place to belong,
interact, share opportunities, talk with peers and develop professionally through
the forms of participation that suit them. These immediate growth goals guide
current product priorities and recommendations; the wider app vision remains
in place.

Members create communities around their own needs. Editable examples help them
get started with a specialty, local network, school, study goal, career stage or
research interest. Examples are suggestions, not automatically created groups;
members choose their own name and purpose, with an optional discovery category.

The longer-term goal is to introduce employer capabilities gradually once the
community is established and trusted, with the controls those capabilities need.
Staff MFA remains explicitly deferred by the user. Record it as pending work;
it is not the next immediate product priority or an implemented protection.

Prioritize improvements that help members:

1. Join easily and discover people and communities relevant to their interests
   and career stage.
2. Experience value early through a useful conversation, response, connection
   or relevant opportunity.
3. Share useful community content and invite peers through convenient mobile
   flows, including WhatsApp/native sharing and continuity after sign-in.
4. Return for helpful replies, ongoing discussions, opportunities and learning,
   with control over notifications.
5. Participate confidently through clear visibility, reporting and moderation.

Evaluate growth through acquisition, first meaningful participation, active
contributors, returning members and invitations that lead to participation.
Establish baselines and instrument missing measurements before drawing growth
conclusions. Registration counts alone do not establish an active community.

## Recovery checkpoint and completed next increment — 17 November 2026

The implemented foundation includes member-created and joinable communities,
interest-based suggestions, unanswered questions, Helpful and selected answers,
learning discussions, and WhatsApp/native/copy invitations with sign-in
continuation. See the [delivery guide](COMMUNITY_ENGAGEMENT.md) for behavior and
verification. Public hosting and real-device/provider validation remain necessary
for a public rollout.

At recovery, the next increment had models in `app/models/participation.py` and
migration `e6480h8d4305` only. Following the user's instruction to complete it,
those foundations now have services, routes, member screens, worker integration
and verification. The [participation delivery guide](COMMUNITY_PARTICIPATION.md)
covers:

- Voluntary mentorship and peer support across career stages.
- Recurring learning activities and attendance.
- New-member goals, introductions and host welcomes.
- Personal invitation attribution and referral participation measurement.
- Optional weekly digests and contribution recognition preferences.

Growth measures distinguish joining from a published first contribution and
returning use. Delivered features and isolated checks do not establish actual
market penetration or retention; a public rollout and real member participation
remain necessary for those outcomes.

Existing authentication, privacy and access controls support this community
experience. Employer expansion has its own later requirements for organization
approval, recruiting authority, applicant-data access and privileged operations.

## Previously authorized delivery scope

The four engagement features requested on 16 November have their own
[delivery guide](COMMUNITY_ENGAGEMENT.md): shared-interest communities, useful
questions and answers, learning activities, and invitation continuity. This
increment delivers those journeys without completing every item below.

Scope authorized on 15 November 2026: implement assessment items 2–7. Item 1 is
explicitly excluded. The current home screen, dashboard priorities, jobs and
career positioning remain as they are.

Delivery checklist:

- [ ] Joinable public communities, hosts/moderators, welcome/rules, pinned resources
      and per-community notification choices; preserve existing posting access.
- [ ] Interest-based community suggestions and optional introduction/first question
      in onboarding, plus a host welcome queue.
- [ ] Unanswered questions, question/experience/celebration post types, saved
      discussions, Helpful/Thank you reactions and accurate contribution recognition.
- [ ] Optional Android/iPhone push, per-category preferences, quiet hours, group
      mute controls and weekly digest through the existing notification worker.
- [ ] Block/mute controls with consistent message, relationship, content and
      notification enforcement; community-scoped moderation and clear public visibility.
- [ ] WhatsApp/native sharing, invitation links with post-login continuation,
      selected public community search indexing after explicit launch configuration.
- [ ] Focused tests, migrations, browser/device-build checks, operational handoff.

Communities stay public in this delivery. Membership is an engagement choice,
not a privacy boundary. A private-community feature would require separate,
end-to-end access control including offline retention; no private group is implied.
No actual invitations, push or digest messages will be sent to real members during
development. Provider delivery will be exercised with isolated test transports.
