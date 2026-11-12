# LSHSC activation review — 7 November 2026

**Exact source:** https://lshsc.ng/recruitment

**Current status:** pending; no live vacancy publication enabled. The URL has not been replaced.

## Findings

The user identifies this as a government-owned source and does not want a separate licence to be mandatory. The review workflow now accepts a documented legal basis, including applicable government-publication rules, as well as published reuse terms or written authorization. It does not assume that all government material is unrestricted. Staff record the applicable reference, finding and permitted scope for the uses the collector actually performs.

The local registry had unknown reuse rights, no approval expiry and no configured vacancy adapter when inspected. Its two existing check failures report HTTPS certificate validation errors. These are reachability observations, not findings that the institution is invalid.

A fresh request to the exact source with curl failed certificate-chain validation both inside and outside the network sandbox. Chrome, with normal certificate verification, loaded the recruitment-guidance page. The capture contains zero schema.org JobPosting records. It describes how recruitment will be announced and says applications should follow an approved exercise and application period. It does not identify a particular open nursing vacancy.

The captured page links to contact and other institutional pages, but no licence/terms link was found on that page. This limited observation does not establish that terms or a lawful basis do not exist. The page's self-description is not independent evidence linking the exact domain to the Commission. No government-ownership rule, institutional cross-reference or specific reuse authorization was verified during this increment.

Local research capture: `/tmp/nurse-lshsc-activation-browser.html`. This temporary file may be removed; the findings above are the durable project record. It was not ingested as a vacancy snapshot or published.

## Remaining activation work

1. Corroborate the Commission's association with the exact source and its recruitment authority using an official institutional reference. Keep any differing domain as evidence, not a replacement for this URL.
2. Record the applicable reuse basis and scope. A separate licence is not compulsory: a supported legal basis may cover the required uses. The current collector collects HTML, retains complete original pages and extracted records, and republishes normalized vacancy content with attribution. Do not attest to broader uses than the evidence supports. A facts-only collector or a retention-limited arrangement would need corresponding implementation before activation under that narrower basis.
3. **TLS transport check completed on 8 November 2026:** the application now supplies the verified missing Sectigo intermediate for the LSHSC hostnames. The actual bounded fetcher passed HTTPS/robots checks and received HTTP 200 with full certificate/hostname verification. See the update below. This does not establish source ownership or automatic-activation eligibility.
4. When an actual recruitment announcement exists, inspect its format. The current JSON-LD collector cannot turn general guidance, a prose announcement or a PDF into a vacancy. Add and test a suitable adapter if the source uses a different format.
5. Approve the reviewed source, configure the collector within its recorded reuse scope and run a bounded worker check. Ordinary valid vacancies then publish automatically; empty pages publish nothing.

No permission request has been sent, no rights holder has been contacted, and no staff approval has been impersonated. Discovery of other potential sources continues independently.

## TLS compatibility update — 8 November 2026

The server presented only its leaf certificate (CN `lshsc.ng`, valid 30 October 2026 through 16 May 2027), omitting the Sectigo Public Server Authentication CA DV R36 intermediate. A normal verified handshake failed with `unable to get local issuer certificate`.

The missing public intermediate was retrieved from the issuer URL advertised in the leaf certificate and cryptographically verified against the machine's existing system roots. Nurse.ng now bundles it exclusively for `lshsc.ng` and `www.lshsc.ng`. Full-chain verification to an existing root is required; partial-chain trust is explicitly disabled, hostname and validity checks remain enabled, and the OS trust store is unchanged. See [certificate provenance and maintenance](../app/certificates/README.md).

The installed production transport was exercised through `PublicFetcher.get('https://lshsc.ng/recruitment')` without monkeypatches. It completed robots checks and followed the website's redirect to `https://www.lshsc.ng/recruitment/`, returning HTTP **200**, **39,032 bytes**, and **zero structured JobPosting records**. The original registered URL is unchanged. An earlier temporary-context probe produced the same result.

This resolves the diagnosed certificate-chain failure on Nurse.ng's side without contacting the website administrator. It does not enable collection/publication by itself: source/redirect association, applicable reuse evidence and an actual supported vacancy remain separate requirements. The exact-origin restriction for automatic activation still requires review of the redirected source. No live source approval, vacancy publication or local registry health rewrite was performed by these read-only transport probes; a running worker records its own current outcome.

## Live background-worker verification — 8 November 2026

The actual CLI `recruitment-worker --once --max-tasks 1` was run against live LSHSC with production-mode settings and disposable migrated queues. The normal spawned child, network transport and installed intermediate were used without implementation overrides. External profile logging observed completed TLS handshakes and HTTP responses without changing SSL settings.

Both `lshsc.ng` and `www.lshsc.ng` completed TLS 1.3 handshakes with certificate validation required, hostname verification enabled and partial-chain trust disabled. The www recruitment page returned HTTP 200 and the persisted worker task completed as `page_checked`. The non-www automatic task returned `scope_blocked` after its HTTP 301 redirect changed origin. In the existing pending staff-review metadata mode, the worker followed that same redirect, received HTTP 200 and completed as `page_checked`; no source was approved or authorized for collection. This separates the successful TLS workaround from the existing automatic-activation redirect policy, which was preserved.

The worker stdout logs, observed handshake settings/HTTP responses and saved task/source events were inspected. The TLS/fetch/worker regression suites passed **63 tests in 12.87 seconds**. No application code or real application database records were changed, and no persistent worker was left running.

Evidence: `/tmp/nurse-lshsc-worker-integration-1kjnipo7/REPORT.md`, the per-case `.worker.log`/`.tls.jsonl`/`.result.json` files and `summary.json`. Runner: `/tmp/nurse-lshsc-worker-integration.py`. Temporary artifacts may eventually be removed; the findings here are the durable record.
