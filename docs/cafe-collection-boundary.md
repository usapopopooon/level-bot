# Cafe Collection boundary

Cafe Collection's Discord and website surfaces are owned by the separate
`cafe-collection-bot`. level-bot retains the transactional data boundary while the
Cafe state and XP wallet share its PostgreSQL database.

## Owned by Cafe Collection

- Card catalog, rarity rules, sets, mastery, medals, draws, collection state,
  redemptions, cosmetics, leaderboards, and public response schemas.
- XP contribution queries exposed by `src.features.cafe_gacha.economy`. Other
  features must not query Cafe Collection model classes directly.
- The remaining public-data adapter exposed by
  `src.features.cafe_gacha.integration`.

## Outbound ports

Core Cafe services use the protocols in `src.features.cafe_gacha.ports` for data not
owned by Cafe Collection:

- `ExternalCardConsumptionPort` accounts for cards consumed by integrations such as
  marimo revival.
- `LeaderboardAudiencePort` supplies inactive or display-excluded users.
- `PublicGuildAccessPort` and `UserPresentationPort` supply host-owned publication
  policy and optional avatar data to the public API.

The current same-process implementations live in
`src.features.cafe_gacha.adapters.level_bot`. A separate bot can provide database,
HTTP, or message-based adapters without changing Cafe domain logic.

The reverse integration is also explicit: marimo revival uses
`src.features.marimo_xp.ports.CafeCardInventoryPort` instead of importing Cafe
Collection services from its core. Its current adapter can later be replaced with a
Cafe service client.

All XP-spending features use `src.features.economy.service` for wallet calculation
and transaction locking. They do not depend on the color-role shop implementation.

## Current extraction state

- level-bot does not install Cafe Discord commands, persistent views, panels, or
  ledger notification workers.
- `cafe-collection-bot` owns every Discord interaction and all 535 JPEG assets.
- New Bot reads and mutations use the dedicated `CAFE_COLLECTION_API_TOKEN`; each
  Discord interaction ID remains the idempotency key.
- `cafe-collection-bot.chill-cafe.site` owns the browser-facing API and image URLs.
  Its catalog, leaderboard, and profile data currently come from level-bot's
  read-only upstream adapter.
- level-bot retains only `manifest.json` so the internal capabilities response can
  detect catalog/image bundle mismatches without packaging duplicate JPEG files.
- Keep `CAFE_COLLECTION_PUBLIC_API_ENABLED=true` while the new API uses that
  read-only upstream. It can be removed only after this data source moves too.

## Remaining intentional coupling

The Cafe state and XP wallet remain in level-bot's PostgreSQL schema. The new Bot
does not write its own Cafe database; it uses the authenticated internal API, which
calls the existing wallet lock and idempotent draw transaction. Moving ownership to
the new database remains a later migration.
