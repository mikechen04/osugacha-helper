# osu! gacha fuel ev bot

A Discord bot (and small CLI) that prices **osu! gacha** farm maps against live market listings.

One **Fuel** restores 60 stamina. Every map costs 10 stamina on a win, so **1 Fuel = 6 runs**. The bot takes the cheapest Fuel buy-now listing as the Fuel cost, then shows expected Stars + drop value per map and difficulty, and profit per Fuel.

Uses your read-only osu! gacha API key (`Authorization: Bearer og_...`) for `/market/listings`. It never buys, sells, or starts fights.

## Commands

| Command | What it does |
| --- | --- |
| `/ev` | Maps ranked by profit after fuel: `# / map / diff / gross ev / profit`. Footer shows the fuel lbin used and the price time |
| `/prices` | lbin for Fuel and the drop items, with % change vs 12h ago (falls back to the oldest snapshot and says e.g. `vs 3h` until 12h of history exists) |

All bot output is lowercase, uses "lbin", and has a pink sidebar.

## How EV is calculated

```
per run ev   = avg stars + sum(avg item qty x item lbin)
gross        = per run ev x 6
after fee    = stars x 6 + items x 6 x 0.98
profit       = after fee - fuel lbin
```

- **lbin** is the lowest buy-it-now listing price **per unit** (a listing of 2 for 14,600 is 7,300 each). Auctions are ignored.
- The 2% market fee applies to sold items only, never to Stars.
- Prices are cached for 5 minutes. A snapshot of every tracked lbin is stored in sqlite (`data/lbin.db`) every 15 minutes, which feeds the % change in `/prices`.
- 429 responses are retried after the `Retry-After` delay.

## Drop tables

The API does not expose drop tables to API keys (`/farm` is blocked), so drops live in [`drops.yaml`](drops.yaml). Copy them from the "Drops a win" panel on the maps page. Ranges are `[min, max]` and the average is used. Add `estimated: true` to a map you are unsure about and `/ev` marks it with a `*`.

```yaml
maps:
  - map: galaxy collapse
    short: gal collapse   # shown in /ev, 12 chars max
    diff: gal             # 5 chars max
    stars: [440, 520]
    items:
      replay_1: [1, 3]
      replay_2: [0, 1]
```

If you have measured a real average from your own farming, give it instead of the range midpoint: `replay_2: {range: [0, 1], avg: 77/120}` (77 drops over 120 runs).

Item ids are the market ids (`fuel`, `replay_1`, `replay_2`, `replay_3`, `insignia_tank_1`, `mod_fragment`, ...). Every id listed under `items:` in the file is priced and shown in `/prices`.

## Run the Discord bot

1. Create an application at the [Discord Developer Portal](https://discord.com/developers/applications) and reset the bot token.
2. Copy `.env.example` to `.env` and fill it in:

```
OSUGACHA_API_KEY=og_...
DISCORD_TOKEN=...
DISCORD_APP_ID=...
```

```bash
python -m venv .venv
.venv\Scripts\activate        # source .venv/bin/activate on mac/linux
pip install -r requirements.txt
python -m osugacha_ev
```

`.env` is gitignored. Never commit it.

### Personal app (Add to My Apps)

The commands are registered as a **user install** app with contexts guild, bot dm and private channel, so they work in any server or dm.

1. Developer Portal > your app > **Installation** (left sidebar).
2. Under **Installation Contexts**, check **User Install**. Save.
3. **Install Link** = Discord Provided Link.
4. **Default Install Settings > User Install**: add the `applications.commands` scope only. Save.
5. Open this and pick **Add to my apps** (not Add to a server):

https://discord.com/oauth2/authorize?client_id=1567013691738558464&scope=applications.commands&integration_type=1

Then type `/ev` in any chat. Commands can take a minute to appear.

## CLI (no Discord)

```bash
python -m osugacha_ev ev
python -m osugacha_ev prices
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```
