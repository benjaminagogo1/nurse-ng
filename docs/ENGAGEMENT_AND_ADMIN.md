# Video likes, visibility and administrator management

Reels and community posts now have Like/Unlike buttons and public counts.
A member has one like per post. The same reel in Reels and the Community feed
shares its count. Repeated requests set the desired state rather than toggling
it, so a retried request cannot add another like or undo one. Guests can see
counts; sign-in and CSRF validation are required to change them. Processing,
failed and removed videos cannot be liked.

Reel uploads remain private while processing. Once ready, they appear in
`/reels`, `/feed` and the selected topic. `/reels/mine` shows the creator's
uploads and their processing status. A video uploaded through `/posts/new`
appears in the Community feed and its topic; use `/reels/new` to publish a reel.
Upload and status pages now explain these destinations.

The member dashboard displays **up to three current opportunities**, selected
by `suggested_opportunities(..., limit=3)`. It shows fewer when fewer jobs are
eligible. The existing link opens the full Jobs page.

## Add an administrator

1. Have the person register a normal account.
2. Open **User overview → Manage administrators**, or **Staff → Administrators**
   at `/staff/admins`.
3. Search by name, email, phone number or user ID.
4. Expand **Make administrator**, review the account, enter your own current
   password and select **Confirm administrator**.

Existing administrators can also remove another person's administrator access.
Self-removal is blocked. Changes are recorded with the acting account, affected
account, action and timestamp. Every role change invalidates the affected
account's previous sessions. A new sign-in is required. Repeated stale forms
cannot silently overwrite a newer role decision. Inactive accounts cannot be
promoted. No real account was promoted or demoted during implementation.

These privileges use the existing `is_staff` role and cover all staff tools;
they are not limited to analytics. The existing CLI remains available for
initial administrator setup and operator recovery.

## Signed-out browsing and notices

Jobs, Reels and Community remain public. Viewing them does not restore a
signed-out session. Personal actions and pages—including applications, saved
jobs, likes, uploads, messages, the dashboard and admin tools—require sign-in.
Jobs now identifies public browsing explicitly and links to sign-in.

Sign-in and sign-out confirmations use short text in a compact card, capped at
25rem wide, centered in the page content with equal side spacing and a dismiss
button. Errors retain their existing
form feedback. The notices remain available to screen readers and are not
automatically dismissed before someone has time to read them.

## Migration and verification

Revision `e6480f6b2183` adds `community_post_likes` and `staff_role_events`.
It was trialled on a database backup, preserving every pre-existing table,
then applied to the local database. Backup:
`.local-backups/before-likes-admin-20261114T070148Z/`.
The backup directory is private and excluded from Git. Existing account roles
are unchanged by the migration. Downgrade refuses to discard recorded likes or
administrative decisions.

The [focused regression report](verification/2026-11-14/engagement-pytest.xml)
records 151 passing checks across likes, admin access, Reels, sign-in,
community, activity, dashboard discovery, migrations and offline behavior.
Chrome runners exercise actual video upload/processing, shared likes and unlike,
administrator grant/revoke, public browsing after logout, and notice layouts
at desktop and mobile widths. Browser evidence is recorded separately in
`docs/verification/2026-11-14/engagement/`.
