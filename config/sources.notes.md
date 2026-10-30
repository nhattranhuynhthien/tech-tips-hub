# Source verification notes

Checked on 2026-10-30 with the configured bot User-Agent. Sources are enabled only when the URL returned HTTP 200 and at least one parsed item had a title, link, and publication date.

## Disabled because the check failed

| ID | Result | Reason |
|---|---|---|
| howtogeek | Connection closed | Endpoint did not return an HTTP response during the check. |
| makeuseof | Connection closed | Endpoint did not return an HTTP response during the check. |
| xdadevelopers | Connection closed | Endpoint did not return an HTTP response during the check. |
| quantrimang | HTTP 200, 0 parsed items | No entry with the required title, link, and date fields. |
| vnexpress_sohoa | HTTP 200, 0 parsed items | No entry with the required title, link, and date fields. |
| reddit-androidtips | HTTP 429 | Rate limited during verification. |
| reddit-iostips | HTTP 429 | Rate limited during verification. |
| reddit-win11 | HTTP 429 | Rate limited during verification. |
| reddit-excel | HTTP 429 | Rate limited during verification. |
| reddit-selfhosted | HTTP 429 | Rate limited during verification. |
| reddit-linux4noobs | HTTP 429 | Rate limited during verification. |
| stack-superuser | HTTP 200, 0 parsed items | Endpoint did not return the required item fields in this check. |
| devto-productivity | HTTP 200, 0 parsed items | Endpoint returned no qualifying article records. |
| mastodon-techtips | HTTP 200, 20 entries | No entry had all required title, link, and date fields. |

## Not enabled because configuration is intentionally empty

- YouTube: no channel IDs were entered or verified. Add only channels whose ID can be confirmed from the official channel page.
- Telegram: No Telegram channel is enabled by default. Add a public channel as a `telegram` source in `config/sources.json` after an administrator chooses it.
- Facebook: scraping and account-based access are intentionally unsupported.

## Other checked sources

The remaining enabled feeds in `config/sources.json` returned HTTP 200 and parsed at least one item with a title, link, and publication date during the check. Re-run `npm run check-source -- <id>` before enabling any source that later becomes disabled.
