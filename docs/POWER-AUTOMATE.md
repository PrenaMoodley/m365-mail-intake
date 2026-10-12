# Would Power Automate do this?

Often, yes. Before writing code, this is the flow I'd consider first:

> **When a new email arrives in a shared mailbox (V2)** (Office 365 Outlook,
> "Include attachments: Yes", "Only with attachments: Yes")
> → **Apply to each** attachment
> → **Condition**: name ends with `.pdf`
> → **Create file** (SharePoint) in `Invoices/<year>/<month>`
> → **Move email (V2)** to "Filed"

That covers the basic job in under an hour, and the finance team can see and
change it. It's the right answer when volumes are low and the rules are simple.

## Why this one is code

| Need | Power Automate | This service |
|---|---|---|
| Skip a re-sent invoice that's identical to one already filed | Awkward: needs a lookup list and content hashing | SHA-256 of the file, checked before upload |
| Catch up safely after an outage | Trigger may miss mail while the flow is off | Delta query resumes exactly where it stopped |
| Don't lose mail when SharePoint is throttling | Retry policy per action, failures easy to miss | Message stays put, delta link doesn't advance, next run retries |
| Tests for the filing rules | Not practical | `pytest`, runs in CI on every change |
| Feed the next step (AI extraction in [po-intake-ai](https://github.com/PrenaMoodley/po-intake-ai)) | Possible with an HTTP action, premium connector | Same Python codebase |

## A sensible middle ground

Keep the trigger in Power Automate (the business can see it) and have it call
this service's webhook or an Azure Function for the parts that need code. Pick
whichever the team that will support it is comfortable with.
