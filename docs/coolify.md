# Coolify deployment

This app is migrated from Railway to Coolify as four services:

```text
postgres  PostgreSQL 18
bot       Discord worker
api       FastAPI public API
frontend  Next.js admin dashboard
```

Production hostnames:

```text
API:   https://level-bot-api.chill-cafe.site
Admin: https://level-bot-admin.chill-cafe.site
```

Do not commit real Discord tokens, database passwords, admin passwords,
session keys, or external API keys.

## First Deploy Before Cutover

Deploy with:

```dotenv
BOT_ENABLED=false
```

This lets Coolify start PostgreSQL, FastAPI, and the admin dashboard while the
Railway bot is still running. The bot container should only print:

```text
bot disabled; set BOT_ENABLED=true after stopping the Railway bot
```

This is intentional. Do not enable the Coolify bot until the Railway bot is
stopped or deleted.

## Required Coolify Variables

Use `.env.coolify.example` as the template.

Required before the API can start in production:

```dotenv
ENVIRONMENT=production
ADMIN_USER=...
ADMIN_PASSWORD=...
SESSION_SECRET_KEY=...
SECURE_COOKIE=true
CORS_ORIGINS=https://level-bot-admin.chill-cafe.site,https://chill-cafe.site
EXTERNAL_API_KEY=...
```

Required before the Discord bot can be enabled:

```dotenv
BOT_ENABLED=true
DISCORD_TOKEN=...
```

Coolify PostgreSQL defaults:

```dotenv
POSTGRES_DB=level_bot
POSTGRES_USER=level
SERVICE_PASSWORD_POSTGRES=...
DATABASE_REQUIRE_SSL=false
```

`DATABASE_REQUIRE_SSL=false` is correct for the internal Docker network.
Railway Postgres may have used SSL, but the Coolify service-to-service
connection does not need it.

## Public API Consumers

After the API is available on Coolify, update consumers:

```dotenv
# intro-bot
LEVEL_API_BASE=https://level-bot-api.chill-cafe.site
EXTERNAL_API_KEY=<same read-only API key>
```

```dotenv
# chill-cafe-site
VITE_LEVEL_BOT_API_ORIGIN=https://level-bot-api.chill-cafe.site
VITE_LEVEL_BOT_API_TOKEN=<same read-only API key>
```

`chill-cafe-site` is a browser app, so any `VITE_*` token is public in
practice. Treat that token as read-only and rotate it separately if possible.

## DNS

`level-bot-api.chill-cafe.site` is hosted through the KAGOYA VPS relay and
Coolify. The `chill-cafe.site` apex is hosted on GitHub Pages and should not be
changed when only the API subdomain is being updated.

Expected API DNS:

```text
level-bot-api.chill-cafe.site A 133.18.125.123
level-bot-api.chill-cafe.site AAAA 2406:8c00:0:3459:133:18:125:123
level-bot-admin.chill-cafe.site A 133.18.125.123
level-bot-admin.chill-cafe.site AAAA 2406:8c00:0:3459:133:18:125:123
```

As of 2026-07-02, both A and AAAA records are published and both public IPv6
paths have been verified:

```sh
curl -6 -k https://level-bot-api.chill-cafe.site
curl -6 -k -I https://level-bot-admin.chill-cafe.site
```

## Database Migration

1. Deploy Coolify with `BOT_ENABLED=false`.
2. Confirm the Coolify PostgreSQL container is healthy.
3. Stop/delete the Railway bot before the final dump.
4. Dump Railway PostgreSQL with a PostgreSQL 18 client:

```sh
docker run --rm -e PGPASSWORD postgres:18-alpine \
  pg_dump -h "$RAILWAY_DB_HOST" -p "$RAILWAY_DB_PORT" \
  -U "$RAILWAY_DB_USER" -d "$RAILWAY_DB_NAME" -Fc > level-bot-railway.dump
```

5. Restore into Coolify:

```sh
pg_restore --clean --if-exists --no-owner --no-acl
```

6. Verify table counts.
7. Set `BOT_ENABLED=true` and redeploy.
8. Confirm Discord Gateway connected and the bot logged `ready`.

## Verification

API health:

```sh
curl -fsS "$LEVEL_BOT_API_ORIGIN/healthz"
```

External API auth:

```sh
curl -fsS \
  -H "Authorization: Bearer $EXTERNAL_API_KEY" \
  "$LEVEL_BOT_API_ORIGIN/api/v1/guilds/GUILD_ID/users/USER_ID/levels"
```

Admin:

```text
https://level-bot-admin.chill-cafe.site
```

Bot logs should include Discord Gateway connection and ready messages after
cutover.
