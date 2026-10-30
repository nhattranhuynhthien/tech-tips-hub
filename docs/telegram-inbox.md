# Telegram community inbox setup

The inbox runs as a Vercel Function at `/api/telegram`. Configure these values in Vercel Project Settings; never commit them:

| Environment variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token created with BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Random secret used to authenticate Telegram webhooks |
| `ADMIN_IDS` | Comma-separated Telegram numeric user IDs |
| `GITHUB_TOKEN` | Fine-grained PAT for this repository with Issues and Contents read/write |
| `GITHUB_REPO` | `owner/repo` for this site |
| `GITHUB_BRANCH` | Optional; defaults to `main` |
| `SUBMIT_LIMIT_PER_DAY` | Optional per-user limit; defaults to 10 |
| `PUBLIC_TELEGRAM_BOT_USERNAME` | Optional public bot username, without `@`, for the submit pages |

Create the bot with BotFather, add the numeric admin IDs, and verify `getWebhookInfo`. Register the webhook with Telegram's `setWebhook` API using:

- URL: `https://meocongnghe.vercel.app/api/telegram`
- Secret token: the same value as `TELEGRAM_WEBHOOK_SECRET`
- Allowed updates: `message` and `callback_query`

GitHub Issues is the pending queue; approval writes only approved records to `data/community.json`. The hourly Python pipeline adds them to the published index. Facebook pages are never fetched; contributors must provide the link and their own short description. Set `PUBLIC_TELEGRAM_BOT_USERNAME` to show the Telegram button on `/vi/submit`, `/en/submit`, and `/gui-trick`.
