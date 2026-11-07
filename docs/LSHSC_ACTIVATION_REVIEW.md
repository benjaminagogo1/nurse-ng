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
3. Obtain a successful HTTPS/robots check through the production fetcher without disabling certificate validation. Browser success alone does not validate the worker's certificate chain or prove source ownership.
4. When an actual recruitment announcement exists, inspect its format. The current JSON-LD collector cannot turn general guidance, a prose announcement or a PDF into a vacancy. Add and test a suitable adapter if the source uses a different format.
5. Approve the reviewed source, configure the collector within its recorded reuse scope and run a bounded worker check. Ordinary valid vacancies then publish automatically; empty pages publish nothing.

No permission request has been sent, no rights holder has been contacted, and no staff approval has been impersonated. Discovery of other potential sources continues independently.
