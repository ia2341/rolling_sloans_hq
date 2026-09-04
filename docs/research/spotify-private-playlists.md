# Showing a Private Spotify Playlist In-Page: What It Demands, and Whether It Discriminates Between Stacks

**Research date:** 2026-09-04
**Ticket:** [#304](https://github.com/ia2341/rolling_sloans_hq/issues/304) (child of map [#302](https://github.com/ia2341/rolling_sloans_hq/issues/302))
**Primary source:** [developer.spotify.com](https://developer.spotify.com) documentation, read 2026-09-04. Two claims are backed by direct HTTP probes against Spotify's own endpoints, marked **[probe]**.

---

## Bottom line up front

**The requirement is STACK-NEUTRAL. It eliminates no candidate stack.**

Everything hard about displaying a private playlist is *server-side custody of an OAuth refresh token* plus *Spotify's Development Mode restrictions*. Neither of those is a frontend concern. What the frontend actually has to render is: a "Connect Spotify" link (an `<a href>` to `accounts.spotify.com/authorize`), a redirect landing route, and a list of song rows. Polished Django templates, Django + React islands, a Django API + React/TS SPA, and Next.js all render that identically, and none of them makes the token custody problem easier or harder.

The one thing that *would* have discriminated — an in-page Spotify Embed / iFrame API widget, which needs a third-party script from `open.spotify.com` and would run into the [#168](https://github.com/ia2341/rolling_sloans_hq/issues/168) no-CDN rejection — is **ruled out anyway** because an Embed cannot render a private playlist. So the constraint that might have created a stack argument dissolves before it gets to one.

There is one genuine *design* consequence for the SPA option, but it is a design note, not a stack elimination: the Spotify integration must stay a **backend-owned** integration. The SPA must not run PKCE in the browser and must not hold the refresh token, because that token is a 6-month, playlist-owner-scoped credential (§1.3). "Django API + React/TS SPA" survives that constraint intact — the SPA just calls our own endpoint and gets rows back, exactly as it will for every other read.

**Collateral finding that matters more than the verdict** (see §5): the Web API changes of February/March 2026 appear to have **already broken the existing `scheduling/spotify.py` public-playlist import**. That is an urgent backend issue independent of this map.

---

## 1. The OAuth shape

### 1.1 Which flow

Client Credentials — what `scheduling/spotify.py` uses today — is definitionally incapable of this. Spotify: *"The Client Credentials flow is used in server-to-server authentication. Since this flow does not include authorization, only endpoints that do not access user information can be accessed."* ([client-credentials-flow](https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow)). A private playlist is user information. There is no link-based escape hatch.

The correct flow is **Authorization Code**, *not* PKCE. Spotify positions PKCE as the flow *"if you're implementing authorization in a mobile app, single page web apps, or any other type of application where the client secret can't be safely stored"* ([code-pkce-flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)); the plain Authorization Code flow requires the client secret and *"must be securely stored on the backend"* ([code-flow](https://developer.spotify.com/documentation/web-api/tutorials/code-flow)). Django *is* a confidential client and already holds `SPOTIFY_CLIENT_SECRET`. PKCE would be the wrong choice here even if the frontend were a SPA — see §4.3.

A redirect URI must be registered and must match exactly. Spotify requires HTTPS *"unless you are using a loopback address, when HTTP is permitted"*, and explicitly: *"`localhost` is not allowed as redirect URI"* — use `http://127.0.0.1:PORT` in dev ([redirect_uri](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)). This is a one-line entry in the Developer Dashboard and a one-route addition in `scheduling/urls.py`.

### 1.2 Which scopes

From [concepts/scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes), verbatim:

| Scope | Description |
|---|---|
| `playlist-read-private` | "Read access to user's private playlists." |
| `playlist-read-collaborative` | "Include collaborative playlists when requesting a user's playlists." |

The [Playlists concept page](https://developer.spotify.com/documentation/web-api/concepts/playlists) is the load-bearing statement on which scope buys what, for listing a user's playlists:

> - Owned and followed non-collaborative public playlists will be returned
> - Owned and followed non-collaborative private playlists will only be returned when the scope `playlist-read-private` has been granted
> - Owned and followed collaborative playlists will only be returned when the scope `playlist-read-collaborative` has been granted

So: request **both**. `playlist-read-private` is mandatory; `playlist-read-collaborative` is required the moment the band's playlist is collaborative — and a Spotify playlist *cannot be both collaborative and public at once*: *"a playlist cannot have both the 'collaborative' attribute and the 'public' attribute set to true at the same time"* (same page). A collaborative band playlist is therefore necessarily non-public, which makes the second scope likely, not optional-in-practice.

**Ambiguity, stated honestly:** the [Get Playlist Items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items) reference page says only "OAuth 2.0" and does **not** enumerate required scopes for that endpoint. The scope→behaviour mapping above is documented for *listing a user's playlists*, not for *reading one playlist's items*. The docs do not state the scope requirement for `GET /playlists/{id}/items` directly. Treat "request both scopes" as the safe reading, and verify empirically against a real private playlist before building on it.

### 1.3 Who grants, and the ownership trap

This is the finding that actually shapes the design, and it is stronger than "a member must log in".

[Get Playlist Items](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items), verbatim:

> **Note**: This endpoint is only accessible for playlists owned by the current user or playlists the user is a collaborator of. A `403 Forbidden` status code will be returned if the user is neither the owner nor a collaborator of the playlist.

And the [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), on playlist responses:

> **Important**: Playlist contents (`items`) are only returned for playlists the user owns or collaborates on. For other playlists, only metadata is returned and the `items` field will be absent from the response.

So the granting user is not "an admin" and not "each member" — it must be **the Spotify account that owns the band playlist, or an account added as a collaborator on it**. A member who merely follows the playlist gets a 403 and no items. This collapses the "who grants?" question: **exactly one grant, by the playlist owner, once.** Per-member OAuth would be actively wrong — most members' tokens would 403.

That is a good outcome for us. One grant means one refresh token, held server-side, used for a background/admin-triggered import. No member ever sees a Spotify consent screen, and no member's Spotify identity enters the portal — which sits well with the project's privacy posture.

### 1.4 Where the refresh token lives, and when it dies

Server-side, in the Django database or an env-injected secret — never in the browser, never in `localStorage`, never in the SPA. It is a single credential that unlocks the playlist owner's private playlists.

Lifetime, from [refreshing-tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens):

- Access tokens: **1 hour** (`expires_in: 3600`). *"Access tokens are intentionally configured to have a limited lifespan (1 hour)"*.
- Refresh tokens: **6 months**, and refreshing does **not** extend that. Verbatim:
  > Refresh tokens issued to apps registered in the Developer Dashboard have a lifetime of 6 months. […] **Creation**: The 6-month lifetime starts when the user authorizes your app. **Refresh**: Your app can exchange the refresh token for new access tokens. Refreshing an access token does not extend the refresh token's lifetime. **Expiration**: After 6 months, the refresh token can no longer be used. **Reauthorization**: Your app must send the user through the authorization flow again.
  > *Info: Build reauthorization into your app before refresh tokens expire. Do not assume that a refresh token remains valid indefinitely.*
- Revocation / expiry surfaces as `invalid_grant` from the token endpoint. Spotify's own example handles it by discarding stored tokens and sending the user back to `/login`.

**Design consequence:** a hard six-month re-consent cycle. For a band portal whose Semesters run roughly that long, that lands somewhere between "once per semester" and "twice per year" — a recurring admin chore, and a failure mode that must degrade to a readable "Spotify needs reconnecting" state rather than a 500. This is a service-layer concern (`scheduling/services.py` / `scheduling/spotify.py`), invisible to whichever frontend renders it.

---

## 2. Development Mode

From [concepts/quota-modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), verbatim:

- *"Newly-created apps begin in **development mode**."*
- **Cap: "Up to 5 authenticated Spotify users can use an app that is in development mode"** — and *"Each Spotify user who installs your app will need to be added to your app's allowlist before they can use it."* (Confirmed by the [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) table: *Users per app: 5* for new apps, with existing apps grandfathered. Note the widely-cited "25 users" figure is **stale** — that was the pre-February-2026 cap.)
- **Premium requirement (new, and easy to miss): *"The app owner must have a Spotify Premium account for apps in development mode to function."*** The migration guide is blunter: *"All Development Mode apps require the app owner to have an active Spotify Premium subscription. If the owner's Premium subscription lapses, the app will stop working. It will resume functioning once the owner resubscribes."*
- Non-allowlisted users: *"Users may be able to log into a development mode app without having been allowlisted by the developer. However, API requests with an access token associated to that user and app will receive a `403` status code error."*
- Development-mode apps are also subject to a shared **quota bucket** returning `429` with `"reason": "QUOTA_EXCEEDED"`, separate from ordinary rate limits.

**Is the 5-user cap a real gate for us? No — because §1.3 means we need exactly one authenticated Spotify user: the playlist owner.** Members never authenticate to Spotify. One allowlist entry, four spare. The cap is a non-issue for this design and only becomes one if someone later proposes per-member Spotify auth, which the ownership rule already rules out.

**Is extended quota mode reachable? Categorically no, and it does not matter.** Verbatim requirements: *"Established Business Entity (legally registered business or organisation)"*, *"Operating an active, and Launched Service"*, *"Maintaining a minimum of active users (at least 250k MAUs)"*, *"Being available in key Spotify markets"*, and — decisive — *"as of May 15th 2025, Spotify only accepts applications from organizations (not individuals)"* with the application *"sent through a company email"*. Review *"can take up to six weeks."* A student band portal with ~25–40 members is not eligible on any of those axes and will never be. **Plan permanently for Development Mode.** The real gates are therefore the Premium-owner requirement and the endpoint restrictions of §5 — not the user cap.

---

## 3. Embed vs Web Playback SDK vs Web API

| | What it shows | What the host page must provide | Can it render a **private** playlist? |
|---|---|---|---|
| **Embed / iFrame API** | Spotify's own rendered widget: playlist artwork, track list, 30s previews (full tracks only for a logged-in Premium viewer) | Just an `<iframe>`. **No client id, no redirect URI, no token.** The iFrame API additionally needs a third-party script: `https://open.spotify.com/embed/iframe-api/v1` | **No** — see below |
| **Web Playback SDK** | Nothing. It is a *playback device*, not a UI: it makes the browser a Spotify Connect target | `https://sdk.scdn.co/spotify-player.js`, an OAuth access token, and *"a Spotify Premium subscription (mobile only types of premium subscriptions are excluded)"* — **per listener** | **No** — it renders no track list at all; you still need the Web API for contents |
| **Web API** | Raw JSON: titles, artists, `duration_ms`, order — exactly what `ImportedSong` needs | Server-side client id + secret, a registered redirect URI, and a stored refresh token | **Yes — and it is the only one that can** |

Sources: [embeds](https://developer.spotify.com/documentation/embeds), [using-the-iframe-api](https://developer.spotify.com/documentation/embeds/tutorials/using-the-iframe-api) (script URL quoted verbatim there), [web-playback-sdk](https://developer.spotify.com/documentation/web-playback-sdk) and [its getting-started tutorial](https://developer.spotify.com/documentation/web-playback-sdk/tutorials/getting-started) (`https://sdk.scdn.co/spotify-player.js`; *"The Web Playback SDK needs an access token from your personal Spotify Premium account"*).

### 3.1 Why an Embed cannot show a private playlist

**The docs never say this in words — that is an honest gap, and I am not going to pretend otherwise.** The Embeds documentation is silent on authentication and silent on private content. The conclusion rests on mechanism plus two probes:

1. The embed carries **no authentication of any kind**. The [oEmbed reference](https://developer.spotify.com/documentation/embeds/reference/oembed) shows the full generated markup, and its only variable is the entity id in `src="https://open.spotify.com/embed/playlist/<id>"`. There is no token parameter, no client id, no signature. The iframe is therefore rendered by `open.spotify.com` for **whoever's browser loads it**, with no assertion that our app or the playlist owner authorized anything.
2. **[probe]** `GET https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M` returns **HTTP 200 with no credentials presented** — confirming the endpoint serves anonymously, i.e. it can only serve what an anonymous visitor may see.
3. The [Creating an Embed](https://developer.spotify.com/documentation/embeds/tutorials/creating-an-embed) flow is "find the content in the Web Player → Share → Embed", i.e. the embed is a *share* artifact. And the Playlists concept page notes the `public` attribute *"does not refer to access control […] anyone with the link to the playlist can access it unless it's made private through for instance the desktop client"* — so a genuinely private (client-side "private"/secret) playlist is precisely the case where link access is withdrawn.

Also worth recording: the oEmbed reference's `url` parameter is documented as *"The URL-encoded URL of a Spotify podcast show, episode, artist, album or track"* — **playlist is not in that list**, though the tutorial says playlists are embeddable and **[probe]** oEmbed does in fact return playlist markup. The reference page is simply out of date. Minor, but it is the kind of thing that erodes trust in a page you were about to build on.

**Verdict: an Embed is not a candidate at all.** It cannot show private contents, and it cannot be made to.

### 3.2 The privacy objection, which independently kills the Embed

Even if an Embed *could* show a private playlist, it would collide head-on with the [#168](https://github.com/ia2341/rolling_sloans_hq/issues/168) rejection of CDNs — *"a CDN would announce every member's IP and referer to a third party on every page load"* (CLAUDE.md). An Embed is worse than a CDN, not equivalent:

- The iFrame API requires loading a **live third-party script from Spotify** (`https://open.spotify.com/embed/iframe-api/v1`) into a page of an auth-gated member portal — exactly the pattern #168 rejected.
- **[probe]** Fetching the embed URL returns `set-cookie: sp_t=…; Path=/; Expires=<+1 year>; Domain=.spotify.com; Secure; SameSite=none` **and** `set-cookie: sp_landing=http%3A%2F%2Fopen.spotify.com%2Fembed%2Fplaylist%2F…%26device%3Ddesktop`. That is a year-long cross-site tracking cookie plus a landing-URL record, set on every member's browser on every page view of any portal page carrying an embed.
- The [Widget Terms of Use](https://developer.spotify.com/documentation/embeds/terms) are a separate legal agreement the project would be accepting on the band's behalf.

So the Embed is out twice over: functionally incapable, and against a standing project decision. **The Web API is the only route, and it is a server-side route.**

---

## 4. The verdict: stack-neutral

### 4.1 What the frontend actually has to do

Strip away the OAuth machinery and the frontend surface of "show the private playlist" is:

1. An admin-only **"Connect Spotify"** control. It is a plain link to `https://accounts.spotify.com/authorize?...`. Not an API call — a full-page navigation, because Spotify's consent screen is Spotify's page.
2. A **callback landing route** that receives `?code=…&state=…`, exchanges it server-side, stores the refresh token, and redirects somewhere useful.
3. A **list of rows** — title, artist, length, position.
4. A **"Spotify needs reconnecting"** empty/error state for the 6-month expiry and for `invalid_grant`.

That is a link, a redirect, a table, and an error state.

### 4.2 Scored against the four candidates

| Candidate | Can it do this? | Anything harder or easier? |
|---|---|---|
| **Polished Django templates** | Yes | Nothing. Steps 1–4 are an `<a>`, a view, a `{% for %}`, and an `{% if %}` |
| **Django templates + React islands** | Yes | Nothing. The island renders rows fetched from our endpoint; OAuth stays a full-page Django flow |
| **Django API + React/TS SPA** *(current preference)* | Yes | One wrinkle, not a cost: the OAuth redirect is a **full-page navigation away from and back into the SPA**. Standard OAuth-in-SPA handling — land the callback on a Django route, then redirect into the app. The token exchange never touches the SPA |
| **Next.js full-stack** | Yes | No advantage. Its route handlers are just a server holding a secret — which Django already is. Nothing about Spotify favours it |

**No candidate is eliminated, and none is meaningfully advantaged.** The requirement does not discriminate.

### 4.3 The one real design note for the SPA option

The temptation in a React/TS SPA is to reach for PKCE and run the flow in the browser, because that is the flow Spotify recommends *for* SPAs ([code-pkce-flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), and its refresh example literally reads `localStorage.getItem('refresh_token')`).

**Do not do that here.** Spotify's PKCE guidance assumes the authenticating user *is* the viewer, holding *their own* token. Ours is the opposite shape: one long-lived, six-month, **playlist-owner-scoped** credential shared by the whole band. Putting that in `localStorage` would hand every portal viewer a credential to the owner's private Spotify library — a far worse leak than any per-user token. Django holds the secret and the refresh token; the SPA calls our endpoint and receives rows.

This is a constraint on *how* the SPA integrates, not an argument against the SPA. It is also exactly the seam CLAUDE.md already names: *"the seam for any future API is `services.py`, endpoint-per-interaction"*.

### 4.4 Therefore

Per the ticket's own instruction — *"If stack-neutral, say so plainly — the backend implementation then leaves this map as an ordinary issue"* — **this is stack-neutral, and the Spotify work should leave map #302 and become an ordinary backend issue.** Map #302 already lists "The Spotify private-playlist backend implementation" under Out of scope; this research confirms that placement rather than disturbing it.

---

## 5. Collateral finding: the existing import is probably already broken

Not what the ticket asked, but it would be negligent to leave it in a footnote.

`scheduling/spotify.py` calls `GET /v1/playlists/{id}/items` with a **Client Credentials** (app-only) token. Per the [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide):

- New Development Mode restrictions applied to **new apps from February 11, 2026**, and **existing Development Mode apps were migrated to them on March 9, 2026**.
- `GET /playlists/{id}/items` is *"Only available for playlists the user owns or collaborates on."*
- *"Playlist contents (`items`) are only returned for playlists the user owns or collaborates on. For other playlists, only metadata is returned and the `items` field will be absent."*
- The [reference page](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items) now states this unconditionally: *"A `403 Forbidden` status code will be returned if the user is neither the owner nor a collaborator."*

A Client Credentials token has **no user at all**, so it can never be an owner or a collaborator. The most likely present-day behaviour of `import_playlist()` is a `403` → `AUTH_FAILED_MESSAGE` ("Spotify rejected the import credentials"), or an empty/`items`-less payload silently yielding zero rows. Either way the current public-playlist import path is very likely dead, and the error message points admins at the wrong cause.

Three further things in that guide touch our code even after a fix:

- The **field rename**: `tracks` → `items`, `tracks.tracks` → `items.items`, `tracks.tracks.track` → `items.items.item`. `_rows_from_items()` already reads `item.get('item')`, so that part is current — worth confirming the rest is.
- **Removed track fields** include `popularity`, `available_markets`, `linked_from` — we use none of them. `duration_ms` and `artists` are untouched.
- **Client IDs per developer** is now capped (1 at February 2026, *"As of July 2026, the Client IDs per developer limit has been increased to 25"*).

**I have not run this against Spotify** — verifying it needs live credentials. It should be reproduced against the real app before anything is built on top of the current module. Recommend filing it as its own backend issue, ahead of the private-playlist work, since the OAuth migration in §1 is also the fix for it: one Authorization Code grant by the playlist owner repairs the public case *and* unlocks the private case in a single change.

---

## 6. Limitations

- **No live API calls with credentials.** Everything about token behaviour, scopes and 403s is read from the docs, not observed. The two **[probe]** claims are unauthenticated HTTP requests to public endpoints and are the only empirically verified items here.
- **The scope requirement for `GET /playlists/{id}/items` is not documented.** §1.2 infers it from the playlist-listing rules. Verify empirically.
- **The Embeds docs never address private playlists.** §3.1's conclusion is mechanism-plus-probe, not a quoted statement. It is strongly supported but it is an inference.
- **Spotify is changing this surface fast** — dated changes in February, March, May and July 2026, with the March 9 migration inside the last six months. Re-check the [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes) and [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) pages before implementing; the "25 users" figure this document corrects was itself accurate not long ago.

## Sources

- [Authorization Code flow](https://developer.spotify.com/documentation/web-api/tutorials/code-flow)
- [Authorization Code with PKCE flow](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Client Credentials flow](https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow)
- [Refreshing tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)
- [Scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes)
- [Playlists (concept)](https://developer.spotify.com/documentation/web-api/concepts/playlists)
- [Redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
- [Quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [February 2026 Dev Mode Changes — Migration Guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [Get Playlist Items (reference)](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items)
- [Get Playlist (reference)](https://developer.spotify.com/documentation/web-api/reference/get-playlist)
- [Embeds](https://developer.spotify.com/documentation/embeds) · [Creating an Embed](https://developer.spotify.com/documentation/embeds/tutorials/creating-an-embed) · [Using the iFrame API](https://developer.spotify.com/documentation/embeds/tutorials/using-the-iframe-api) · [oEmbed reference](https://developer.spotify.com/documentation/embeds/reference/oembed) · [Widget Terms of Use](https://developer.spotify.com/documentation/embeds/terms)
- [Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk) · [Getting started](https://developer.spotify.com/documentation/web-playback-sdk/tutorials/getting-started)
