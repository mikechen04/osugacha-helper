"""discord bot. a user installed (personal) app with /ev and /prices."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from osugacha_ev import fmt
from osugacha_ev.app import App, Report
from osugacha_ev.config import ALERT_POLL, CARD_DEFAULT_PCT, CARD_POLL, PINK, SNAPSHOT_EVERY, Settings

log = logging.getLogger("osugacha_ev")


def embed_of(report: Report) -> discord.Embed:
    embed = discord.Embed(
        title=report.title,
        description=report.description,
        colour=discord.Colour(PINK),
    )
    if report.footer:
        embed.set_footer(text=report.footer)
    return embed


class EvBot(discord.Client):
    def __init__(self, settings: Settings):
        super().__init__(intents=discord.Intents.default(), application_id=settings.discord_app_id)
        self.app = App(settings)
        self.tree = app_commands.CommandTree(
            self,
            allowed_installs=app_commands.AppInstallationType(guild=False, user=True),
            allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=True
            ),
        )
        self._register()

    def _register(self) -> None:
        @self.tree.command(name="ev", description="fuel ev per map, ranked by profit")
        @app_commands.describe(likely_to_sell="only count drops that actually sell (default true)")
        async def ev(interaction: discord.Interaction, likely_to_sell: bool = True) -> None:
            await self._send(interaction, lambda: self.app.ev_report(likely_to_sell))

        @self.tree.command(name="prices", description="lbin for fuel and drops")
        async def prices(interaction: discord.Interaction) -> None:
            await self._send(interaction, self.app.prices_report)

        item_choices = [
            app_commands.Choice(name=name, value=item_id)
            for item_id, name in list(self.app.table.names.items())[:25]
        ]

        @self.tree.command(name="besttime", description="best utc hours to sell or buy an item")
        @app_commands.describe(item="which item, default fuel")
        @app_commands.choices(item=item_choices)
        async def besttime(
            interaction: discord.Interaction, item: app_commands.Choice[str] | None = None
        ) -> None:
            item_id = item.value if item else "fuel"
            await self._send(interaction, lambda: self.app.besttime_report(item_id))

        @self.tree.command(name="bp", description="cheapest battle power upgrades for a player's team")
        @app_commands.describe(username="osu gacha username, or leave empty to use your linked one")
        async def bp(interaction: discord.Interaction, username: str | None = None) -> None:
            name = (username or "").strip() or self.app.store.get_link(interaction.user.id)
            if not name:
                await interaction.response.send_message(
                    fmt.lc("give a username, or link yours with /link username"), ephemeral=True
                )
                return
            await self._send(interaction, lambda: self.app.bp_report(name))

        @self.tree.command(name="link", description="link your osu gacha username for /bp")
        @app_commands.describe(username="your osu gacha username")
        async def link(interaction: discord.Interaction, username: str) -> None:
            await interaction.response.defer(ephemeral=True)
            try:
                found = await self.app.find_user(username)
            except Exception:
                log.exception("link lookup failed")
                await interaction.followup.send(fmt.lc("could not reach the site, try again soon"))
                return
            if not found:
                await interaction.followup.send(fmt.lc(f"no player named {username.strip()}"))
                return
            self.app.store.set_link(interaction.user.id, found)
            await interaction.followup.send(fmt.lc(f"linked to {found}. /bp now uses it by default"))

        @self.tree.command(name="unlink", description="remove your linked osu gacha username")
        async def unlink(interaction: discord.Interaction) -> None:
            had = self.app.store.get_link(interaction.user.id)
            self.app.store.set_link(interaction.user.id, None)
            await interaction.response.send_message(
                fmt.lc("unlinked" if had else "nothing was linked"), ephemeral=True
            )

        @self.tree.command(name="alerts", description="ping me when fuel is quicksold")
        @app_commands.describe(
            mode="turn pings on or off",
            percent="how far under the next lbin, default 10",
        )
        @app_commands.choices(
            mode=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")]
        )
        async def alerts(
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            percent: app_commands.Range[int, 1, 90] = 10,
        ) -> None:
            user_id = interaction.user.id
            if mode.value == "off":
                self.app.store.set_alert(user_id, None)
                text = "fuel pings off"
            else:
                self.app.store.set_alert(user_id, float(percent))
                text = f"fuel pings on, {percent}% under the next lbin"
            await interaction.response.send_message(fmt.lc(text), ephemeral=True)

        @self.tree.command(
            name="cardalerts", description="ping me when a mythic or divine card is undercut"
        )
        @app_commands.describe(
            mode="turn pings on or off",
            percent=f"how far under the next cheapest card of that rarity, default {CARD_DEFAULT_PCT}",
        )
        @app_commands.choices(
            mode=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")]
        )
        async def cardalerts(
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            percent: app_commands.Range[int, 1, 90] = CARD_DEFAULT_PCT,
        ) -> None:
            user_id = interaction.user.id
            if mode.value == "off":
                self.app.store.set_card_alert(user_id, None)
                text = "card pings off"
            else:
                self.app.store.set_card_alert(user_id, float(percent))
                text = f"card pings on for mythic and divine, {percent}% under the next cheapest"
            await interaction.response.send_message(fmt.lc(text), ephemeral=True)

    async def _send(self, interaction: discord.Interaction, build) -> None:
        await interaction.response.defer()
        try:
            report = await build()
            await interaction.followup.send(embed=embed_of(report))
        except Exception:
            log.exception("command failed")
            await interaction.followup.send(fmt.lc("could not reach the market, try again soon"))

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self.snapshots.start()
        self.fuel_watch.start()
        self.card_watch.start()

    @tasks.loop(seconds=SNAPSHOT_EVERY)
    async def snapshots(self) -> None:
        try:
            count = await self.app.snapshot()
            if count:
                log.info("stored lbin snapshot (%d items)", count)
        except Exception:
            log.exception("snapshot failed")

    @tasks.loop(seconds=ALERT_POLL)
    async def fuel_watch(self) -> None:
        try:
            pings = await self.app.fuel_alerts()
        except Exception:
            log.exception("fuel watch failed")
            return
        for user_id, report in pings:
            try:
                user = await self.fetch_user(user_id)
                await user.send(content=f"<@{user_id}>", embed=embed_of(report))
                log.info("pinged %s about a fuel quicksell", user_id)
            except Exception:
                log.exception("could not dm %s", user_id)

    @tasks.loop(seconds=CARD_POLL)
    async def card_watch(self) -> None:
        try:
            pings = await self.app.card_alerts()
        except Exception:
            log.exception("card watch failed")
            return
        for user_id, report in pings:
            try:
                user = await self.fetch_user(user_id)
                await user.send(content=f"<@{user_id}>", embed=embed_of(report))
                log.info("pinged %s about a card undercut", user_id)
            except Exception:
                log.exception("could not dm %s", user_id)

    @card_watch.before_loop
    async def _before_card_watch(self) -> None:
        await self.wait_until_ready()

    @fuel_watch.before_loop
    async def _before_fuel_watch(self) -> None:
        await self.wait_until_ready()

    @snapshots.before_loop
    async def _before_snapshots(self) -> None:
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        log.info("ready as %s", self.user)

    async def close(self) -> None:
        self.snapshots.cancel()
        self.fuel_watch.cancel()
        self.card_watch.cancel()
        await self.app.aclose()
        await super().close()


def run(settings: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    EvBot(settings).run(settings.discord_token, log_handler=None)
