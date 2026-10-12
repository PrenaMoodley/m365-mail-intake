# Permissions: least privilege for an unattended Microsoft 365 app

The service runs with no user signed in, so it uses **application permissions**
and the OAuth 2.0 client credentials flow. Application permissions are powerful
by default (`Mail.ReadWrite` alone would cover *every* mailbox in the tenant), so
each one is scoped down.

## App registration (Microsoft Entra ID)

| Permission (application) | Why | Scoped to |
|---|---|---|
| `Mail.ReadWrite` | Read messages and attachments, move handled mail to "Filed" | The invoices mailbox only, via Exchange RBAC for Applications (or an application access policy) |
| `Sites.Selected` | Write files to the document library | One SharePoint site, granted explicitly by a SharePoint admin |

No `Sites.ReadWrite.All`, no `User.Read.All`, no delegated permissions.

### Limit mail access to one mailbox

With Exchange Online PowerShell, an Exchange admin restricts the app to a
management scope containing only the shared mailbox (RBAC for Applications).
Without this step the app could read the CEO's mail.

### Grant the one SharePoint site

A SharePoint admin grants the app `write` on the single site (through the Graph
`sites/{site-id}/permissions` endpoint or PnP PowerShell). Until that grant
exists, `Sites.Selected` gives access to nothing.

## Secrets

- Prefer a **certificate** over a client secret in production; if a secret is
  used, give it a short expiry and put the renewal date in the runbook.
- Store it in the host's secret store (Azure Key Vault, GitHub Actions secrets),
  never in the repository or a `.env` file that gets copied around.
- The webhook's `clientState` is a separate random secret, so a forged
  notification can't trigger runs.

## Review checklist before go-live

- [ ] App can read the invoices mailbox, and gets 403 on any other mailbox.
- [ ] App can write to the invoices library, and gets 403 on another site.
- [ ] Secret or certificate expiry date is in the runbook and someone's calendar.
- [ ] Sign-in logs for the app's service principal are monitored.
