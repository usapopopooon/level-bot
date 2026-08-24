# Cafe Collection boundary

Cafe Collection remains in the level-bot repository for now, but its integration
points are explicit so the Discord feature and the public HTTP API can move to a
separate bot in stages without changing current behavior.

## Owned by Cafe Collection

- Card catalog, rarity rules, sets, mastery, medals, images, draws, collection state,
  redemptions, cosmetics, leaderboards, and public response schemas.
- XP contribution queries exposed by `src.features.cafe_gacha.economy`. Other
  features must not query Cafe Collection model classes directly.
- Installation metadata and feature switches exposed by
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

## Staged extraction

1. Deploy the new Cafe bot with Discord command registration disabled while keeping
   `CAFE_COLLECTION_BOT_ENABLED=true` in level-bot.
2. Immediately before enabling Discord commands in the new bot, set
   `CAFE_COLLECTION_BOT_ENABLED=false` in level-bot to prevent duplicate command and
   persistent-component registration.
3. Keep `CAFE_COLLECTION_PUBLIC_API_ENABLED=true` in the level-bot API until catalog,
   image, leaderboard, and profile routes have moved.
4. Point the port implementations and XP contribution API at the new service.
5. Set `CAFE_COLLECTION_PUBLIC_API_ENABLED=false` only after traffic has moved.

## Remaining intentional coupling

The current deployment still uses one PostgreSQL schema and one atomic XP wallet.
Splitting the database or allowing both bots to write XP concurrently requires an
explicit transactional API or reservation protocol; feature flags alone are not a
safe substitute for that coordination.
