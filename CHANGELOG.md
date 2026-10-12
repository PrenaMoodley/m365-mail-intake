# Changelog

## [Unreleased]

### Backlog
- Upload sessions for attachments over 4 MB.
- Subscription renewal job and a health check that alerts when the subscription lapses.
- Certificate credentials instead of a client secret.
- Hand filed invoices to po-intake-ai for extraction.

## [0.1.0] - 2026-10-13

### Added
- Microsoft Graph client: app-only OAuth, paging, delta queries, throttling retries.
- Intake run: PDF-only, SHA-256 de-duplication, SharePoint filing by year/month/supplier, move to "Filed".
- Change-notification webhook with validation handshake and clientState check.
- Least-privilege permissions guide and Power Automate comparison.
- CI on Python 3.11 and 3.13.
