# Account photos, email recovery and deletion

Members manage these features at `/settings`. The login page links to
`/auth/forgot-password`. Sign-in still uses a phone number and password; recovery
sends a link to the account's verified email address.

## Action feedback

Photo upload/removal/visibility, contact changes, email verification, password
reset and deletion now use consistent status cards. Each card has an icon,
plain-language result and next step. The page brings the result directly below
the header, including when the action was submitted near the bottom of Settings.
Success and informational cards stay until dismissed or the member navigates;
error cards remain while the member corrects the problem. Settings also shows
the current photo visibility and persistent verified-email status.

With JavaScript enabled, submit buttons show the current operation and prevent
duplicate submissions. Invalid fields have nearby messages and accessible
descriptions. Offline and interrupted requests retain the entries and selected
photo. An interrupted response is described as unconfirmed because the server
may already have saved the change; the app never automatically retries it.
Ordinary HTML forms still work without JavaScript.

Successful mutations put a one-time message in the signed session for the
destination page. Only the matching page consumes it, after successful rendering.
Query parameters such as `?photo=saved` or `?reset=1` do not create success claims.
Messages contain no passwords or verification tokens. Password resets clear the
old session before adding their confirmation. Email requests say that a link was
requested; they do not claim confirmed inbox delivery.

## Upgrade

Install `requirements.lock` (including Pillow), back up the database and media,
then run `./venv/bin/alembic upgrade head`. The account-management revision is
`7bd28ea64c10`. Restart the application after upgrading. Existing accounts and
sessions are preserved; existing email addresses start unverified and photos
start private. Downgrade refuses to discard stored photos, verified-email or
session-revocation state, or queued file removals.

## Enable real email delivery

Email defaults to disabled. The dashboard recovery reminder is hidden while
delivery is disabled and after the member verifies an email. Settings still
explains delivery availability. Set the following in the deployment environment or
the local ignored `.env`, using the SMTP service's actual values:

```dotenv
NURSE_NG_ACCOUNT_MAIL_BACKEND=smtp
NURSE_NG_PUBLIC_BASE_URL=https://nurse.ng
NURSE_NG_SMTP_HOST=smtp.example.com
NURSE_NG_SMTP_PORT=587
NURSE_NG_SMTP_SECURITY=starttls
NURSE_NG_SMTP_USERNAME=provider-username
NURSE_NG_SMTP_PASSWORD=provider-secret
NURSE_NG_SMTP_FROM=Nurse.ng <verified-sender@your-domain.example>
```

Replace the example sender with the exact address verified in your provider's
sender list. The display name and address can differ from the SMTP login.
Use a sender/domain authorised by the provider and complete its domain and mail
authentication setup. Store credentials in the deployment's secret store, never
in source control. For implicit TLS, use `NURSE_NG_SMTP_SECURITY=ssl` and the
provider's port (usually 465). Both transports require normal certificate and
hostname validation. There is no plaintext SMTP mode.

`PUBLIC_BASE_URL` must be the origin members can reach; production requires
HTTPS. Local development can use `http://127.0.0.1:8000`. Links never derive their
origin from the incoming Host header. Run `./venv/bin/python -m app.cli
check-config`, restart the app, then verify delivery with an operator-controlled
test account: save an email in settings, request verification, follow the link,
and request a password reset. Configuration validation and mocked SMTP tests do
not establish inbox delivery.

### Brevo

In Brevo, open **SMTP & API → SMTP**. Use the SMTP login shown there and an
SMTP key. An API key is a separate credential and will not work as the SMTP
password. Set these values in the ignored `.env` or deployment secret settings:

```dotenv
NURSE_NG_SMTP_HOST=smtp-relay.brevo.com
NURSE_NG_SMTP_PORT=465
NURSE_NG_SMTP_SECURITY=ssl
NURSE_NG_SMTP_USERNAME=your-brevo-smtp-login
NURSE_NG_SMTP_PASSWORD=your-brevo-smtp-key
NURSE_NG_SMTP_FROM=Nurse.ng <your-verified-sender@example.com>
```

The sender must be authorised in Brevo; it can differ from the SMTP login.
Keep `NURSE_NG_ACCOUNT_MAIL_BACKEND=disabled` until the real credentials and
sender are configured, then change it to `smtp` and restart the application.
Use the correct public URL as described above. The local development URL only
works when the verification link is opened on the computer running Nurse.ng.

See [Brevo's SMTP instructions](https://developers.brevo.com/docs/smtp-integration).

### Local development without delivery

For development without a provider:

```dotenv
NURSE_NG_ENVIRONMENT=development
NURSE_NG_ACCOUNT_MAIL_BACKEND=file
NURSE_NG_PUBLIC_BASE_URL=http://127.0.0.1:8000
NURSE_NG_ACCOUNT_MAIL_DIR=private-mail
```

This writes private `.eml` files; it sends no email. The directory is ignored by
Git and must stay outside public/static storage. The directory and files use
0700 and 0600 permissions respectively. Delete development messages when no
longer needed. Production refuses this backend.

## Member recovery flow

1. While signed in, add an email under **Account settings**. Changing an email
   requires the current password and clears verification and outstanding links.
2. Select **Send verification email**, then confirm using the emailed link.
3. If the password is forgotten, enter the sign-in phone number on **Forgot
   password**. A link goes to the verified email address. The response is the
   same for unknown accounts and accounts without a verified email.
4. Set a new password using the link, then sign in again. Resetting the password
   revokes existing sessions on all devices and clears login lockout.

Email-verification links expire after 24 hours; reset links after 30 minutes.
Links work once, and a new request replaces an earlier link for that purpose.
Only token hashes are stored. Links are bound to the email and authentication
version. Tokens arrive in URL fragments and are removed from the address bar by
the page; a manual-code field supports browsers without JavaScript. GET requests
do not consume links. Forms require CSRF protection.

An account can request one email per 60 seconds. Additional process-local IP
limits restrict email and credential attempts; shared IP counters remain an
operational consideration for multiple web workers. SMTP delivery runs after
the HTTP response using FastAPI background tasks. This is not a durable email
queue: failed delivery invalidates that token, and the member can request a new
link after the cooldown. Logs omit addresses, tokens and provider replies.

An account that never verified an email cannot use this recovery flow. No
unverified legacy address is silently trusted.

## Profile photos

Settings supports upload, preview, replacement, removal and public visibility.
Photos are private by default. JPEG, PNG and still WebP are accepted, up to 5 MB
and 16 megapixels by default. Images are decoded, oriented, cropped to 512 × 512
and saved as fresh JPEGs without embedded metadata. Public photos appear beside
the member's profile, community identity and messages; private photos remain
visible only to their owner.

`NURSE_NG_AVATAR_DIR` defaults to `media/avatars` and must remain outside static
storage. The application checks visibility on every photo request and disables
response caching. Keep this storage persistent and accessible to all web
workers. `NURSE_NG_AVATAR_MAX_BYTES` changes the upload byte limit; update the
displayed limit if changing the default.

## Account deletion and storage cleanup

**Review account deletion** opens a confirmation page requiring the current
password and the literal word `DELETE`. The transaction deletes the account,
profile, review documents, connections, messages, applications, owned jobs,
posts and their discussion threads. Replies to an owned thread disappear with
that thread. Administrative actions concerning other accounts retain their
records with the deleted staff reference cleared. Existing cookies cannot
authenticate a deleted user.

File-removal requests are recorded in the same database transaction. Cleanup
runs after commit; failed filesystem operations remain queued for retry. Run
the following with the same database, storage paths and service identity as
the application, and schedule it regularly (for example, every five minutes):

```bash
./venv/bin/python -m app.cli cleanup-account-files
```

Each run processes up to 100 queued entries. Inspect `account_file_deletions`
for a growing backlog and fix storage/permission problems. A reported removal
count of zero alone does not prove that the queue is empty. Account deletion
applies to the live app; operators must manage backup retention and removal
separately. Copies already saved by other people cannot be recalled.

## Verification

Run the focused integration and migration checks with:

```bash
./venv/bin/python -m pytest tests/test_account_management.py tests/test_account_migration.py
```

These use isolated databases and development mailboxes. SMTP tests verify the
transport configuration without sending external messages. Live provider
delivery must be checked after SMTP setup.

For the repeatable Chrome feedback checks, run:

```bash
./venv/bin/python tests/browser/account_feedback.py
```

This uses a temporary database/server, private file mailbox and Chrome profile.
It checks mobile/desktop layouts, contrast, visible placement below the header,
validation, offline input preservation, a paused upload, duplicate submissions,
and a lost response after the server commits. It completes photo, verification,
reset and deletion flows using test accounts and sends no external email.
