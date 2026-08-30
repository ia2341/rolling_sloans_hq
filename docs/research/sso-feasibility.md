# MIT SSO (Touchstone) Feasibility for a Volunteer-Run Student Club App

**Research date:** 2026-08-30
**Scope:** Is integrating MIT Touchstone (Shibboleth/SAML, now Okta-backed) practical for a small (~25–40 user), volunteer-run, free/open-source club web app — vs. a simple email allowlist + password + invite-email baseline?

## Bottom line up front

MIT does offer institution-wide SSO — **MIT Touchstone**, a SAML 2.0 / Shibboleth-based service that, as of a 2024 migration, is backed by Okta Identity Engine internally (login now happens at `okta.mit.edu` instead of `idp.mit.edu`) ([ist.mit.edu/touchstone](https://ist.mit.edu/touchstone), [ist.mit.edu/news/touchstone-okta](https://ist.mit.edu/news/touchstone-okta)). Registering as a service provider (SP) is *technically* open to anyone who emails `touchstone-support@mit.edu` with the right technical details — there is no explicit, published requirement for DLC (department/lab/center) sponsorship or formal approval gating in the provisioning documentation IS&T publishes ([wikis.mit.edu Provisioning Steps for Shibboleth SP](https://wikis.mit.edu/confluence/display/TOUCHSTONE/Provisioning+Steps+for+Shibboleth+SP)).

However, "technically open" is not the same as "practical for a volunteer club." The registration process requires you to already be running a production-grade Shibboleth SP (v3.x), with a valid SSL certificate matching your hostname, NTP-synced clocks, self-generated signing/encryption certificates, and coordination by email with IS&T staff to get an Okta external ID provisioned — a multi-step, human-in-the-loop process with no self-service portal, no stated SLA, and no documented path for informal/unofficial student projects. Compare this to a simple email allowlist + password + invite flow, which requires zero external coordination, zero certificate lifecycle management, and no institutional relationship. For a 25–40 person club, Touchstone is disproportionate infrastructure: real but non-trivial setup cost, an ongoing certificate/metadata maintenance burden, and dependency on an MIT staff contact — all to authenticate a small, mostly-known group who could just as easily be added to an allowlist.

**Recommendation-relevant framing:** SSO via Touchstone is *not* clearly inaccessible (no hard "DLC sponsorship required" wall was found in primary docs), but it is also not lightweight. Given the club's stated priorities (volunteer-run, low-maintenance, free/OSS), the email allowlist + password + invite-email approach is the pragmatic choice unless there's outside pressure (e.g., wanting official MIT recognition/support) to formalize it later.

---

## 1. What does MIT actually offer for third-party/student-project SSO integration?

MIT's SSO offering is **MIT Touchstone**, described by IS&T as "the Institute's single sign-on (SSO) web authentication service" that lets the MIT community log in to participating MIT and federated websites/applications using MIT Kerberos credentials ([ist.mit.edu/touchstone](https://ist.mit.edu/touchstone)).

- **Protocol:** Touchstone is built on **Shibboleth**, i.e. **SAML 2.0**. IS&T's provisioning guide is explicitly titled "Provisioning Steps for Shibboleth SP" and requires the applicant to install and run **Shibboleth SP software version 3.x** ([wikis.mit.edu](https://wikis.mit.edu/confluence/display/TOUCHSTONE/Provisioning+Steps+for+Shibboleth+SP)).
- **Backend identity engine:** As of the 2024 migration, Touchstone is "powered by Okta Identity Engine, a modern, cloud-based and extensible platform" ([ist.mit.edu/news/touchstone-okta](https://ist.mit.edu/news/touchstone-okta); also reported by [The Tech](https://thetech.com/2024/07/11/touchstone-system-okta-powered)). This is Okta acting as the *internal* IdP engine behind Touchstone — it does **not** mean MIT exposes a generic public Okta OIDC tenant for arbitrary third-party app registration. The user-facing/SP-facing protocol contract is still SAML/Shibboleth; the login page moved from `idp.mit.edu` to `okta.mit.edu`, MIT certificate/Kerberos-ticket (SPNEGO) authentication was dropped, but "no action will be required by the developers or integrators who maintain applications and services currently configured to use Touchstone" ([ist.mit.edu/news/touchstone-okta](https://ist.mit.edu/news/touchstone-okta)). No MIT IS&T page found publishes a general-purpose OIDC/OAuth endpoint for external app registration analogous to "Sign in with MIT" — Touchstone/Shibboleth SAML is the mechanism.
- Identity providers: MIT operates (at least) two IdPs — the core MIT IdP for students/faculty/staff/Kerberos-username holders, and a separate `TouchstoneNetwork` IdP hosting the Collaboration Accounts Management System (CAMS) for external self-registered accounts (non-`@mit.edu` email only) (per search of [wikis.mit.edu](https://wikis.mit.edu/confluence/display/TOUCHSTONE/) content).
- MFA: Touchstone is integrated with Duo for MFA ([ist.mit.edu/touchstone](https://ist.mit.edu/touchstone), [ist.mit.edu/duo-security/duo](https://ist.mit.edu/duo-security/duo)).

## 2. Is it realistically accessible to a student club project without MIT IT approval or DLC sponsorship?

The published provisioning documentation does **not** state a formal DLC-sponsorship or departmental-approval requirement as a precondition — it reads as an operational checklist rather than a gated approval workflow:

- Registration is done by **emailing `touchstone-support@mit.edu`** directly with a defined set of technical details: a contact email (IS&T recommends a group/mailing list, not an individual), the web server hostname matching your SSL certificate's Subject CN, self-signed SP signing/encryption certificates (public certs only, not private keys), organization name and URL, the attributes you need released (minimum `eduPersonPrincipalName`), and the Moira group(s) that should have access (individual usernames are explicitly not accepted — access must be managed via Moira groups) ([wikis.mit.edu Provisioning Steps for Shibboleth SP](https://wikis.mit.edu/confluence/display/TOUCHSTONE/Provisioning+Steps+for+Shibboleth+SP)).
- The document does not name an approval authority, an approval timeline, or a DLC-sponsor field. IS&T support handles creating the integration and providing the Okta external ID.
- That said, several practical/implicit barriers exist even without a formal gate:
  - You must **already have a working Shibboleth SP 3.x deployment** (installed, running, with valid TLS, correct clock sync, and a reachable metadata endpoint) *before* IS&T will register you — this is real infrastructure work, not a checkbox.
  - Access control is managed via **Moira groups**, MIT's institutional group-management system — a club would need someone with the standing/knowledge to create and maintain a Moira group of its ~25–40 members, which itself is an MIT-account-holder-only mechanism, not something a fully open/volunteer-run OSS project can self-serve without an MIT-affiliated maintainer.
  - The process is entirely **human-mediated by email** with no self-service portal, published SLA, or guarantee that IS&T will accept a request from an informal, non-DLC-recognized student club (the FAQ/KB content that might spell out eligibility restrictions sits behind MIT's internal ServiceNow portal, `mit.service-now.com`, which required authentication and could not be read as a primary source in this research — see Limitations below).
  - No evidence was found of a self-service "register your app" flow analogous to, e.g., Google/GitHub OAuth app registration; this is closer to an enterprise IT provisioning process.

**Conclusion:** Nothing in the public primary documentation says "student clubs are disallowed," but nothing says they're explicitly welcomed either — the process assumes a technically capable, institutionally-embedded requester (an org with a group mailing list, Moira group management capability, and an existing SP deployment). It is *plausibly* accessible to a persistent, technical club member willing to email IS&T and go through the checklist, but it is not a lightweight, self-service, or clearly-sanctioned path for an informal 25–40 person club project.

## 3. Integration cost/complexity if pursued, vs. the email-allowlist baseline

**Protocol & library support:**

- Touchstone requires **SAML 2.0 via Shibboleth SP**, not OIDC. This constrains implementation choices — a Shibboleth SP is traditionally deployed as `mod_shib` under Apache/nginx as a separate native process/module in front of your app, or you must implement SAML SP logic directly in your framework via a library.
- **Node/Express + Passport:** `@node-saml/passport-saml` is the current actively maintained fork (the original `passport-saml` package is stale — last published ~4 years ago at time of search). `@node-saml/passport-saml` has been tested against Shibboleth-based IdPs among others ([npmjs.com/package/@node-saml/passport-saml](https://www.npmjs.com/package/@node-saml/passport-saml), [passportjs.org/packages/passport-saml](https://www.passportjs.org/packages/passport-saml/)). Usable, but SAML-in-Node integration (XML signing/canonicalization, metadata exchange, certificate config) is meaningfully more complex than an OIDC/OAuth flow.
- **Python (Django/Flask):** `djangosaml2` (IdentityPython org on GitHub) is a community-maintained SP built on `pysaml2`, with ~38k weekly downloads and no known vulnerabilities as of a June 2025 scan ([github.com/IdentityPython/djangosaml2](https://github.com/IdentityPython/djangosaml2), [snyk.io/advisor/python/djangosaml2](https://snyk.io/advisor/python/djangosaml2)). It is real and maintained, but SAML/XML configuration (metadata, attribute maps, signing certs) is inherently heavier than a password/session or OIDC integration.
- **Ruby on Rails:** `ruby-saml` (SAML-Toolkits org) and `omniauth-saml` are the standard libraries and are actively maintained — but 2025 saw **three CVEs in ruby-saml** (CVE-2025-25291, CVE-2025-25292: SAML authentication-bypass via XML-parser differential/signature-wrapping attacks; CVE-2025-25293: DoS via compressed SAML responses), fixed in ruby-saml 1.18.0, requiring `omniauth-saml` to bump its dependency too ([github.com/SAML-Toolkits/ruby-saml](https://github.com/SAML-Toolkits/ruby-saml), [github.blog security post](https://github.blog/security/sign-in-as-anyone-bypassing-saml-sso-authentication-with-parser-differentials/)). This illustrates a real risk pattern specific to SAML: XML signature/parsing bugs are a recurring, high-severity vulnerability class in SAML SP libraries across ecosystems, requiring vigilant patching — a burden a volunteer-run project explicitly wants to avoid.

**Ongoing maintenance burden (Shibboleth SP specific, not framework-specific):**

- **Certificate rotation:** Shibboleth SP certificate rollover is a **multi-step, non-atomic process**. Per SWITCH's (a Shibboleth-federation operator) guide, rollover "may take between several days and several weeks so that updated metadata can propagate to federation IdPs," and "if you aren't familiar with the process then allow at least a month" ([help.switch.ch/aai/guides/sp/certificate-rollover](https://help.switch.ch/aai/guides/sp/certificate-rollover/)). A cert must be regenerated from the *same key* or it breaks SP↔IdP communication until the IdP re-records the new cert.
- **Metadata management:** SAML metadata (which embeds the SP's certificate) should be refreshed regularly — federation guidance recommends at least daily automatic updates, and metadata carries a `validUntil` that must not be allowed to expire ([search summary of Shibboleth/UK federation/SWITCH docs](https://www.ukfederation.org.uk/content/Documents/GetCertificatesSh2SP), [shibboleth.atlassian.net IdP Key and Certificate Management](https://shibboleth.atlassian.net/wiki/spaces/KB/pages/3043917826/IdP+Key+and+Certificate+Management)).
- **Software upkeep:** Running Shibboleth SP itself means maintaining a native service (Apache/nginx module + shibd daemon) as an additional deployment component, separate from and in front of the application server — extra infrastructure a "simple web app" wouldn't otherwise need at all.
- Net effect: even after initial registration succeeds, a Shibboleth/SAML integration commits the club to periodic (roughly annual-scale) certificate/metadata maintenance tasks that carry real risk of breaking login if mishandled, plus SAML-library security patching (as the 2025 ruby-saml CVEs show) — work items with no equivalent in a plain password + email flow.

**Baseline comparison — email allowlist + password + invite-email:**

- No external registration process, no institutional contact, no approval wait.
- No SAML libraries, no XML signing, no certificate rollover, no metadata endpoints.
- Standard, extremely well-trodden implementation: allowlist table + bcrypt/argon2 password hashing + transactional invite email (e.g. via any mail-sending library/service) — all first-party code the club fully owns and can reason about, using ordinary, framework-native session/auth patterns (Passport local strategy, Django's built-in auth, Devise, etc.) rather than a federated protocol.
- Ongoing maintenance is essentially zero beyond normal dependency updates — no cert expiry clocks, no external party whose config changes (Touchstone's own Okta migration in 2024 is a live example of an SSO backend change) can break your login unexpectedly.

## 4. Is SSO realistically accessible for this club without institutional backing?

**Qualified no, in practical terms** — not because MIT documentation states an explicit ban, but because of the combined weight of process and ongoing-ops factors found in primary sources:

1. No self-service registration exists; it is a manual, email-based request to IS&T with no published eligibility statement for informal student clubs, and no documented approval timeline ([wikis.mit.edu provisioning guide](https://wikis.mit.edu/confluence/display/TOUCHSTONE/Provisioning+Steps+for+Shibboleth+SP)).
2. Access control depends on **Moira groups**, an MIT-internal group-management system, which effectively requires an MIT-affiliated person maintaining institutional infrastructure alongside the club's own app — a step beyond what a purely OSS, community-run project would otherwise need.
3. Even after approval, the club would own a **Shibboleth SP deployment** (a native service, not just app code) with a **certificate rollover process that can take weeks and is not forgiving of mistakes**, plus SAML-library security-patch vigilance (concretely demonstrated by the 2025 ruby-saml CVEs) — burdens explicitly at odds with "volunteer-run, low-maintenance."
4. Nothing found in the primary documentation suggests MIT offers a lighter-weight, self-service OIDC alternative for small/unofficial projects; Okta's role at MIT is as the *internal engine behind Touchstone*, not a general-purpose external app-registration surface.

Given the club is small (25–40 known members), volunteer-run, and prioritizes low maintenance, the email allowlist + password + invite-email approach avoids all of the above without meaningfully compromising security for this use case (a closed, small, known-membership group), whereas Touchstone/Shibboleth SSO would add a disproportionate one-time integration cost and a real, recurring operational burden (certs, metadata, SAML library patching) for a benefit — "log in with your MIT ID" — that a well-run allowlist substantially replicates for a group this size.

---

## Limitations of this research

- MIT's internal Knowledge Base FAQ content (`kb.mit.edu` → redirects to `mit.service-now.com` ServiceNow Employee Center) could not be read — it requires MIT Touchstone authentication itself, so any eligibility/restriction language specific to student clubs that might live there was not directly verifiable. This is a real gap: it's possible more explicit restrictions (or explicit permissions) exist there.
- No MIT IS&T page was found that explicitly and separately states "student clubs may/may not register as a Touchstone SP" — the assessment above is inferred from the operational requirements of the published provisioning process (Moira groups, direct IS&T email contact, SP infrastructure prerequisites) rather than from an explicit eligibility rule.

## References

- MIT IS&T — Touchstone Authentication overview: https://ist.mit.edu/touchstone
- MIT IS&T — "MIT's Touchstone system to be powered by Okta starting on June 17": https://ist.mit.edu/news/touchstone-okta
- The Tech — "MIT's Touchstone system to be powered by Okta starting June 17th": https://thetech.com/2024/07/11/touchstone-system-okta-powered
- MIT Wiki Service — Provisioning Steps for Shibboleth SP (Touchstone): https://wikis.mit.edu/confluence/display/TOUCHSTONE/Provisioning+Steps+for+Shibboleth+SP
- MIT Wiki Service — Touchstone Help: https://wikis.mit.edu/confluence/display/TOUCHSTONE/Touchstone+Help
- MIT IS&T (legacy/AFS mirror) — MIT Touchstone: https://stuff.mit.edu/afs/athena/project/touchstone/www/
- MIT IS&T — Touchstone-enabled applications list: https://web.mit.edu/touchstone/www/applications.html
- MIT IS&T — Duo Security: https://ist.mit.edu/duo-security/duo
- npm — @node-saml/passport-saml: https://www.npmjs.com/package/@node-saml/passport-saml
- passportjs.org — passport-saml package docs: https://www.passportjs.org/packages/passport-saml/
- GitHub — IdentityPython/djangosaml2: https://github.com/IdentityPython/djangosaml2
- Snyk Advisor — djangosaml2 package health: https://snyk.io/advisor/python/djangosaml2
- GitHub — SAML-Toolkits/ruby-saml: https://github.com/SAML-Toolkits/ruby-saml
- GitHub Blog (Security) — "Sign in as anyone: Bypassing SAML SSO authentication with parser differentials" (ruby-saml CVE writeup): https://github.blog/security/sign-in-as-anyone-bypassing-saml-sso-authentication-with-parser-differentials/
- GitLab Advisory Database — CVE-2025-25291 (ruby-saml): https://advisories.gitlab.com/pkg/gem/ruby-saml/CVE-2025-25291/
- GitLab Advisory Database — CVE-2025-25293 (ruby-saml DoS): https://advisories.gitlab.com/pkg/gem/ruby-saml/CVE-2025-25293/
- SWITCH (Swiss NREN, Shibboleth federation operator) — Shibboleth SP Certificate Rollover guide: https://help.switch.ch/aai/guides/sp/certificate-rollover/
- UK Federation — Certificates in a Shibboleth 2.x SP installation: https://www.ukfederation.org.uk/content/Documents/GetCertificatesSh2SP
- Shibboleth Consortium Knowledge Base — IdP Key and Certificate Management: https://shibboleth.atlassian.net/wiki/spaces/KB/pages/3043917826/IdP+Key+and+Certificate+Management
