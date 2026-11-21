# Live classroom browser dependency

`livekit-client.umd.js` is the unmodified browser UMD distribution from the
official npm package **livekit-client 2.25.0**. Its Apache 2.0 license is retained
in `livekit-client.LICENSE`.

SHA-256 of the vendored JavaScript:

`45ae7540ab3feded1ee740fdca2a59072179833f6159bc04f137b361fe224e02`

The bundle is local so classroom loading does not depend on a third-party CDN.
It does not contain account credentials, provider keys, or preconfigured rooms.
`education-room.js` targets this SDK's room/track/processor lifecycle contracts.

To update, install a specifically pinned release in a temporary directory,
review its release notes and license, copy its official UMD bundle and license,
record the new version/hash here, and exercise browser room/media tests. Do not
hand-edit the generated bundle. The source map URL in the official bundle is a
development aid; production operation does not require the map file.
