# Google and LinkedIn sign-in

The Google and LinkedIn controls on registration and sign-in now start an
authorization-code flow. Settings → Connected sign-ins lets a signed-in member
connect a provider or disconnect it after confirming their Nurse.ng password.

Existing linked identities sign in directly. A first-time provider identity opens
an account-completion screen: authenticate an existing Nurse.ng account to link it,
or supply a phone number and password to create a new account. Provider email
matches never silently link accounts. New profiles remain private, phone numbers
remain unverified, and selecting an employer role does not grant staff access.

## Provider setup

1. Install `requirements.lock` and run `venv/bin/alembic upgrade head`.
2. Set `NURSE_NG_PUBLIC_BASE_URL` to the actual site origin. Production needs HTTPS
   and a `lax` or `none` session SameSite setting; `strict` blocks the provider return.
3. Register a Google OAuth web application and configure its consent screen. Add
   the exact authorized redirect URI `<origin>/auth/social/google/callback`.
4. Register a LinkedIn application with the **Sign In with LinkedIn using OpenID
   Connect** product. Add `<origin>/auth/social/linkedin/callback` as a redirect URL.
5. Set the provider's client ID and secret in the environment:

   ```dotenv
   NURSE_NG_GOOGLE_CLIENT_ID=
   NURSE_NG_GOOGLE_CLIENT_SECRET=
   NURSE_NG_LINKEDIN_CLIENT_ID=
   NURSE_NG_LINKEDIN_CLIENT_SECRET=
   ```

6. Restart the web process and exercise each provider with approved test accounts,
   then with a second browser and an actual phone. Provider app publishing, domain
   verification, consent-screen approval and account eligibility are external steps.

The local origin currently configured is `http://127.0.0.1:8000`; use local callback
URLs only if the provider permits them. A public deployment requires its own URLs
and credentials. Do not reuse arbitrary redirect URLs supplied by browser requests.

No provider credentials were configured during this implementation. The buttons
remain visible and actionable: missing configuration produces a clear message and
the ordinary phone sign-in form. **Live Google/LinkedIn sign-in is not verified yet.**

## Security and operations

Flows request `openid profile email`. The server verifies RS256 signatures using
the provider's fixed JWKS endpoint and checks issuer, audience, expiry, issued-at,
nonce and any authorized-party claim. A verified provider email is required.
Provider access and refresh tokens are not retained. Fixed endpoints prevent
browser input from selecting token or key servers; token requests refuse redirects.

Random state is stored as a hash, bound to a browser session and consumed once.
Authorization uses PKCE S256. Attempts and account-completion tickets expire after
10 minutes; starting another flow cleans expired records. These short-lived tables
contain private identity data and belong in the protected application database.
Session changes and password-reset session versions invalidate in-flight linking.
Disabled accounts cannot use linked sign-in. Account deletion cascades to linked
identities and attempts. Disconnecting requires the current Nurse.ng password.

Configure web/proxy access logs to omit query strings on callback routes: OAuth
authorization codes arrive in the callback query. Application messages do not
display provider responses, client secrets or tokens.

Run `venv/bin/python -m pytest tests/test_social_auth.py` for callback, linking,
creation, replay, expiry, denial, disconnect and real signed-token validation tests.
Provider transport is substituted in these tests; they do not contact Google or
LinkedIn and cannot establish provider-console configuration.
Callback regression checks use a fresh database session per request with the
production expiration behavior, including enrollment, sign-in, linking, denial
and rejection of a reused callback.
