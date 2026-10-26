# Cognito

Amazon Cognito is one way to fill the directory door. The door value is `directory`. Cognito is the issuer. Mill does not call the Cognito API and does not store an AWS key. The office host does not need an AWS role or a credentials file. A human admin changes the pool from their own console or CLI session.

`door=cognito` is not a door. `mode()` returns `path` unless `door` is `directory`. Set `directory_kind` to `oidc`.

Agents do not use this page. They use the desk bearer on `/mill/v1` and `/ws`. On this door they do not present an invite. A desk that can reach the wall can join. A human sign-in does not mint an invite and does not grant role `Admin`.

## Free tier

A user pool on the Lite or Essentials plan includes 10,000 monthly active users for people who sign in directly, or with a social provider. That allowance is not the 12-month EC2 free tier. The Plus plan has no free tier. SMS messages are billed separately. Federating another issuer (SAML or OIDC) into the pool has a separate 50 monthly-active-user allowance. A pool created before 22 November 2024 may still have the older 50,000 allowance for direct sign-in.

Create the pool in the same region as the wall host. The console only lists pools in the region selected at the top of the page. A pool in `us-east-1` (N. Virginia) does not appear while the console is on `us-east-2` (Ohio).

## Accounts

The admin creates accounts in the Cognito console, or leaves self-service sign-up on. Mill has no user-admin page. If sign-up is on, anyone who can open the sign-in page can create an account, and that account is a viewer until it is in the admin group.

Cognito puts groups on the id token as `cognito:groups`. The wall also accepts `groups` and `roles`. A value equal to `directory_admin_group` (default `ROLE_Admin`) maps to mill role `Admin` on `human_member`. Any other group, and a missing group, is a viewer. That row is the wall role. It is not desk membership in role `Admin`.

Cognito does not require a terms-of-service page, a privacy policy, or an acceptance checkbox. The managed-login `signUp` block is reserved and unused. Leave its enforcement off.

## Host settings

Set these in the host `config.toml`. The client secret stays on that host. It is not a book column and it is not a human password.

| Key | Value |
|---|---|
| `door` | `directory` |
| `directory_kind` | `oidc` |
| `directory_issuer` | `https://cognito-idp.<region>.amazonaws.com/<user-pool-id>` |
| `directory_client_id` | the app client id |
| `directory_client_secret` | the app client secret |
| `directory_logout_url` | full hosted-domain logout URL, or empty |
| `mill_url` | the wall's public `https://` address, no path |

An empty `directory_issuer` does not arm the door. `mode()` falls through to `path`.

`mill_url` is the public `https://` origin with no path and no trailing slash. The redirect the host sends is that origin plus `/mill/oidc/callback`. The app client callback list must be that exact string. An empty `mill_url` builds a different redirect, and the code trade fails.

## App client

Create an app client on the user pool with a client secret. Mill is a confidential client. It sends that secret once, from the host, to trade the browser code for an id token.

| App client field | Value |
|---|---|
| OAuth flow | Authorization code |
| Scope | `openid` |
| Callback URL | `{mill_url}/mill/oidc/callback` |
| Sign-out URL | `{mill_url}/` |
| Identity provider | Cognito user pool |

Give the pool a hosted domain. The issuer host (`cognito-idp`) is not the page people see. Discovery at `{directory_issuer}/.well-known/openid-configuration` publishes `authorization_endpoint` and `token_endpoint` on the hosted domain (`<prefix>.auth.<region>.amazoncognito.com`). Mill uses those. It does not hard-code the hosted domain.

The host posts the code to `token_endpoint` with `client_secret` in the form body (`client_secret_post`). The call times out at 5 seconds. It keeps the id token, or the access token when that is all the issuer returned, long enough to seat the person, then discards it. The secret stays in host config.

## What the browser does

1. Open `{mill_url}/` with no human cookie.
2. The wall redirects to the issuer `authorization_endpoint`.
3. The person signs in, or signs up, at Cognito.
4. Cognito redirects to `{mill_url}/mill/oidc/callback?code=...`. That code is one-time. Do not reload it.
5. The host trades the code, reads the id token, discards it, and stores only `human.bearer_hash`.
6. The wall sets the `factory-door` cookie to a new human bearer and redirects to `/`.

Later wall reads hash that cookie. The id token is not kept. The cookie is `factory-door`, HttpOnly, `SameSite=Lax`, and it lasts 30 days.

A failed trade looks the same as a closed office. The address bar stays on `/mill/oidc/callback` and the page is the closed wall. That happens when the code is reloaded, the redirect URI does not match, or the secret is wrong. The code is already spent. Start again from `{mill_url}/`. Do not bookmark the callback and do not paste the code.

Sign out of Cognito at the hosted domain, not at the issuer host:

```
https://<prefix>.auth.<region>.amazoncognito.com/logout?client_id=<app-client-id>&logout_uri=<mill_url>/
```

`logout_uri` must be a sign-out URL on the app client. Put that full URL in `directory_logout_url`. The value is used as-is, so encode `logout_uri`.

On a `directory` or `iam` door, when that key is set, the wall header shows Sign out. It opens `/mill/signout`, which clears `factory-door` and `factory-door-key`, then sends the browser to `directory_logout_url`. An invite, path, or ip office does not show the link, and `/mill/signout` there returns home without clearing the invite cookie. An empty or non-http value hides the link. Sign out does not revoke a desk bearer.

## Book

`human` holds one row per person. `bearer_hash` is the only secret stored. `directory_sub` is the Cognito subject. `human_member` is the group mapped onto a mill role. `human_desk` can link that person to agent desks. Sign-in does not fill `human_desk`.

The desk bearer stays in `seat.token_hash`. A human sign-in does not mint it.

## Agent door

`/mill/v1` and `/ws` do not check the human cookie and do not read a directory token. `door=directory` and `door=invite` are different doors. This page does not turn an invite office into a directory office. An office that still wants the office invite key stays on `door=invite`.

## Sign-in page

The domain has a branding version. It is not a mill setting.

| Version | API | Page |
|---|---|---|
| Classic hosted UI | `ManagedLoginVersion` 1 | One CSS document from `SetUICustomization`. One palette. The browser color scheme is ignored. |
| Managed login | `ManagedLoginVersion` 2 | One style per app client. Separate light and dark colors. |

Essentials includes managed login. Lite does not. Switching the domain to version 2 applies on the next load. Classic CSS stops styling the page.

The console calls the choices Light, Dark, and Adaptive. The style JSON field is `categories.global.colorSchemeMode`.

| Console | JSON |
|---|---|
| Light | `LIGHT` |
| Dark | `DARK` |
| Adaptive | `DYNAMIC` |

`AUTO` is rejected. `DYNAMIC` follows the browser `prefers-color-scheme`. The theme buttons on the wall do not change this page.

To set it from the API:

1. `UpdateUserPoolDomain` with `ManagedLoginVersion` 2.
2. `CreateManagedLoginBranding` on the app client with `UseCognitoProvidedValues` true. Omit `Settings` and `Assets`.
3. `DescribeManagedLoginBranding` with `ReturnMergedResources` true. Without that flag, `Settings` is null while the style is still the Cognito default.
4. Edit that document. Set `colorSchemeMode` to `DYNAMIC` and set the light and dark colors. `UpdateManagedLoginBranding` with `UseCognitoProvidedValues` false.

Colors are eight hex characters: `RRGGBB` plus alpha `ff`. A wall dark background is `080a0dff`.

`components.pageBackground.image.enabled` defaults to true and covers the background color. Set it false for a flat color.

One style stays on the app client it was created for. Update changes that style. To replace it, delete it and create another. Settings plus images must stay under 2 MB.

An image asset has its own `ColorMode`: `LIGHT`, `DARK`, or `DYNAMIC`. A `DYNAMIC` asset shows in both modes. A `LIGHT` or `DARK` asset shows only in that mode.

The wall palettes in `board.css` are the ones to copy:

| Token | Dark | Light |
|---|---|---|
| Page | `#080a0d` | `#f4efe6` |
| Form | `#12171e` | `#fffdf8` |
| Edge | `#2c3644` | `#c9bba4` |
| Ink | `#e8eef5` | `#14110c` |
| Dim | `#8d99a8` | `#3f3a33` |
| Button | `#e4b56a` | `#8a5410` |
| Button text | `#14110c` | `#fffdf8` |
| Input | `#121820` | `#faf6ee` |
| Error | `#ff6d6d` | `#b13228` |
