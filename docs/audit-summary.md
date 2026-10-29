# Reconceptualizing Nurse.ng as a professional-networking platform

A nurse professional community with documented review, follow/connect features,
and staff moderation — designed for trusted, offline-friendly use.

## Current state

The app is fully functional: login, posts, replies, reports, moderation, and
profile management all work through the test suite. Two bugs prevented public
access before this audit: schema drift between SQLAlchemy models and Alembic
migrations (community_name_key / community_name_locked columns were defined on the
model but never in a migration), and the multi-head Alembic revision confusion.

Those are now resolved and login works end to end over HTTP. What remains is the
explicit user ask: the UI/UX is not ready for the kind of product that will hold
active nurses. That's what this audit fixes next.
