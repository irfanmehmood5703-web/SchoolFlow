# SchoolFlow owner handover and security status — 14 November 2026

## Open and control the system

- Web software: https://schoolflow-phase1.onrender.com/
- Central software owner sign-in: https://schoolflow-phase1.onrender.com/vendor/login
- Private school sign-in: https://schoolflow-phase1.onrender.com/auth/institute
- Source: https://github.com/irfanmehmood5703-web/SchoolFlow
- Hosting: https://dashboard.render.com/web/srv-dbi3dqks728c73c7snv0
- Database project: https://console.neon.tech/app/projects/delicate-block-71773937

Keep the central software-owner password separate from each school's owner password. A school account does not grant central provisioning, hosting or source access. Use the central owner page to create ISF SCHOOL SYSTEM with a new Institute Code and a password entered privately by the owner. Do not put real students in DEMO or the existing fictional QA school.

## Verified, read-only observations

- GitHub repository owner is `irfanmehmood5703-web`; connected access reports administration rights, but the connector does not expose repository administration mutations. Repository visibility is **public**.
- Original Render service deploys the repository's main branch and uses the free web service plan. No infrastructure account ownership transfer has been performed or claimed.
- Neon project ownership email matches the existing central software-owner login email. One central owner and one fictional private school exist; no ISF private institute existed during inspection. Passwords were neither retrieved nor reset.
- PostgreSQL project is on the Free plan. Recovery history is **21,600 seconds (6 hours)**. The inspected branch has **no automatic snapshot schedule**. Recovery history is not an independent backup.
- Available Git history (165 reachable commits) was scanned for high-confidence provider-token and private-key formats, with zero matches. This limited pattern scan is not proof that all secret formats or externally retained copies are clean.
- Existing controls include password hashing, CSRF, durable per-peer/per-account login throttles, school separation, staff scopes, owner session expiry/version revocation and private response caching controls. Functional regression evidence is in SYSTEM_ACCEPTANCE_AUDIT.md.

## Application hardening in this change

Dependency scanning identified vulnerable Flask 3.1.0, Bleach 6.2.0 and Pillow 12.3.0 pins. Updated pins are Flask 3.1.3, Bleach 6.4.0 and Pillow 13.0.0, with the school APK branding worker using the same Pillow version. CI now audits resolved application dependencies before running the full regression corpus. Bleach is at its final upstream release; future sanitizer replacement requires separate validation.


Preserve stricter `no-referrer` and private-file sandbox policies instead of overwriting them with a weaker global default. Add baseline CSP restrictions for document base URLs, plugins and embedding ancestors. Allow camera/microphone/geolocation only for the same origin, preserving attended capture workflows; deny payment/USB browser APIs. Advertise HSTS on HTTPS requests only, without imposing it on child/custom domains. Existing frame-based printing stays same-origin. These controls do not replace access control or a full penetration test.

## Owner-only actions still required

1. Sign in to the main email, GitHub, Render, Neon and eventual domain registrar using the owner's own devices. Enable 2FA/passkeys, store recovery codes offline and verify recovery email/phone. Tool access cannot attest these account settings, and no authentication factor was changed.
2. On GitHub, verify installed integration access for private repositories and Render's GitHub connection. Arrange APK hosting before changing visibility: current generic test APK links are public GitHub Releases links. Making the repository private without replacing those links stops anonymous downloads. School-specific signed download handling must also be checked. Then make the repository private and apply appropriate branch protections. Reading branch protection through this integration returned HTTP 403, so its current status is **unknown**.
3. Choose an independent, owner-controlled backup destination and retention. Current Neon documentation says scheduled snapshots require a paid plan, and snapshot storage is billed. No paid schedule, snapshot, hosting upgrade or backup destination was created. An encrypted scheduled export to an independently controlled location is an alternative; it is not configured yet. A recovery drill must use a separate destination and must never overwrite the live school.
4. Choose/register the domain in the owner's registrar account, then connect DNS/HTTPS and verify login, Android host allowlists and callbacks. No domain has been purchased or custom-domain ownership asserted.
5. Retain Android production signing/recovery keys under owner control. Current generic builds remain test builds; device/SIM/camera acceptance is still outstanding.

## No credential sharing in chat

Passwords, OTPs, recovery codes, database URLs and signing keys belong in their service's secure account/settings surface. Do not paste them into this report, issues, source or chat. If central owner access is lost, use a verified account-recovery procedure; do not silently replace the existing owner's credentials.
