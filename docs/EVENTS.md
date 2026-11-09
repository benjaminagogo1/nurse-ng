# Community events

`/events` lists upcoming published events, with the next three shown on the member
dashboard. Events are available from the main navigation on desktop and mobile.
The existing Upcoming events area now reads real event records.

Staff can publish events at `/events/new`, edit details and cancel events. Details
include a title, description, venue or joining instructions, start/end times and
an optional HTTPS registration link. The editor and display use Nigeria time
(WAT, Africa/Lagos); the database and calendar downloads use UTC.

Members can RSVP or withdraw their RSVP. Attendance names are private; the event
shows only a count. RSVP is idempotent and requires a current account and CSRF
token. Cancelled or ended events cannot receive new RSVPs. Cancelling retains
the detail page with a visible cancellation notice and removes the event from
upcoming listings. A cancelled event cannot be republished by editing it.

An RSVP is an attendance intention, not a paid ticket or a substitute for an
organiser's registration. A supplied registration link opens the organiser's site.
Calendar downloads are standard `.ics` files, with escaped text, folded UTF-8
lines, stable event IDs and cancellation status. Downloads do not automatically
sync later changes. The page tells members to check details before attending.
No email invitations, tickets, payments or external calendar writes are sent.

Upgrade to `e6480ac93d25`. Existing users and records are preserved, and no sample
events are inserted. Run `venv/bin/python -m pytest tests/test_events.py` and
the browser checks described in [quality verification](QUALITY_VERIFICATION.md).
