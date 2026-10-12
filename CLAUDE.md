# m365-mail-intake

Files supplier invoice PDFs from a shared Microsoft 365 mailbox into SharePoint
using Microsoft Graph (app-only OAuth).

## Commands

- Install: `pip install -e ".[dev]"`
- Test: `python -m pytest -q` (Graph is faked with `httpx.MockTransport`; tests must never call a tenant)
- Lint: `python -m ruff check . && python -m ruff format --check .`

## Rules

- Use application permissions scoped to one mailbox and one site. Never suggest
  `*.All` permissions; see `docs/PERMISSIONS.md`.
- Only advance the delta link when every message in the run was handled.
- A message is moved to "Filed" only after all its PDFs are uploaded.
- Handle 429/503 with `Retry-After`. Never retry 4xx errors other than 429.
- The webhook must answer the validation handshake and check `clientState`
  in constant time, then return 202 and work in the background.
- No real mailbox addresses, tenant IDs or secrets in code, tests or docs.
