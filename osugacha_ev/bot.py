"""discord bot. a user installed (personal) app with /ev and /prices."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from osugacha_ev import fmt
from osugacha_ev.app import App, Report
from osugacha_ev.config import PINK, SNAPSHOT_EVERY, Settings

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
        async def ev(interaction: discord.Interaction) -> None:
            await self._send(interaction, self.app.ev_report)

        @self.tree.command(name="prices", description="lbin for fuel and drops")
        async def prices(interaction: discord.Interaction) -> None:
            await self._send(interaction, self.app.prices_report)

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

    @tasks.loop(seconds=SNAPSHOT_EVERY)
    async def snapshots(self) -> None:
        try:
            count = await self.app.snapshot()
            if count:
                log.info("stored lbin snapshot (%d items)", count)
        except Exception:
            log.exception("snapshot failed")

    @snapshots.before_loop
    async def _before_snapshots(self) -> None:
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        log.info("ready as %s", self.user)

    async def close(self) -> None:
        self.snapshots.cancel()
        await self.app.aclose()
        await super().close()


def run(settings: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    EvBot(settings).run(settings.discord_token, log_handler=None)
