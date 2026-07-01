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
API:   https://level-bot-api.usapo.space
Admin: https://level-bot-admin.usapo.space
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
CORS_ORIGINS=https://level-bot-admin.usapo.space,https://chill-cafe.site
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
LEVEL_API_BASE=https://level-bot-api.usapo.space
EXTERNAL_API_KEY=<same read-only API key>
```

```dotenv
# chill-cafe-site
VITE_LEVEL_BOT_API_ORIGIN=https://level-bot-api.usapo.space
VITE_LEVEL_BOT_API_TOKEN=<same read-only API key>
```

`chill-cafe-site` is a browser app, so any `VITE_*` token is public in
practice. Treat that token as read-only and rotate it separately if possible.

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
curl -fsS https://level-bot-api.usapo.space/healthz
```

External API auth:

```sh
curl -fsS \
  -H "Authorization: Bearer $EXTERNAL_API_KEY" \
  "https://level-bot-api.usapo.space/api/v1/guilds/1168847276291137586/users/USER_ID/levels"
```

Admin:

```text
https://level-bot-admin.usapo.space
```

Bot logs should include Discord Gateway connection and ready messages after
cutover.
