# Recruitment TLS compatibility

`sectigo-public-server-authentication-ca-dv-r36.pem` is a public **intermediate**, not a website certificate, private key or additional root. Only recruitment connections to `lshsc.ng` and `www.lshsc.ng` load it. Complete-chain validation to the existing system roots and hostname/expiry checks remain enabled. The application never fetches certificates or modifies system trust at runtime.

- Subject: Sectigo Public Server Authentication CA DV R36
- Issuer: Sectigo Public Server Authentication Root R46
- Validity: 22 March 2021 through 21 March 2036
- SHA-256 of DER: `8C54C334B66BA4E426772AF4A3F9136C19A1AEC729FDB28C535C07A5A4EF22E0`
- Retrieved 8 November 2026 from the issuer URL advertised by the site's leaf certificate: <http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt>

The issuer's HTTPS endpoint failed its handshake. Retrieval used its advertised HTTP endpoint; authenticity was established by successful cryptographic validation against the existing system CA bundle, not by trusting that download. Conversion used `openssl x509 -inform DER`. Validation used:

```bash
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt \
  app/certificates/sectigo-public-server-authentication-ca-dv-r36.pem
```

Update this asset only after checking the issuer, fingerprint, CA constraints, validity and complete chain against maintained system roots. A source changing issuer while still omitting its chain can require a replacement intermediate. Never compensate by disabling certificate checks, enabling partial-chain trust, or bundling the website's leaf certificate as trusted.
