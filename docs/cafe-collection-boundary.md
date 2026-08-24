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

1. Deploy the level-bot API with a dedicated `CAFE_COLLECTION_API_TOKEN`.
2. Deploy the new Cafe bot with the same value in `LEVEL_BOT_API_TOKEN`. Its
   `/cafe draw` and `/cafe collection` commands can run alongside the old panel
   because all reads and writes go through level-bot's transactional API.
   API-created draws remain pending for the existing five-minute notification retry
   loop, so level-bot publishes them to the configured public ledger exactly once.
3. Keep `CAFE_COLLECTION_BOT_ENABLED=true` in level-bot while the old panel,
   exchanges, customization, leaderboards, and public ledger remain there.
4. Keep `CAFE_COLLECTION_PUBLIC_API_ENABLED=true` until catalog, image,
   leaderboard, and profile traffic has moved.
5. Disable the old Bot adapter only after feature parity and notification cutover.
6. Set `CAFE_COLLECTION_PUBLIC_API_ENABLED=false` only after public traffic moves.

## Images during dual operation

Both repositories package the same 361 card JPEGs plus `card-back.jpg` and
`panel-cabinet.jpg` (363 files total). Each repository checks the same SHA-256
manifest in CI, and the new Bot compares the manifest digest with level-bot before
registering Discord commands. A mismatched image build fails closed.

The existing public image API remains authoritative during dual operation. The new
Bot serves the identical immutable image paths for later traffic switching and uses
its local copy for Discord attachments and collection shelf rendering.

## Remaining intentional coupling

The Cafe state and XP wallet remain in level-bot's PostgreSQL schema. The new Bot
does not write its own Cafe database; it uses the authenticated internal API, which
calls the existing wallet lock and idempotent draw transaction. Moving ownership to
the new database remains a later migration.
