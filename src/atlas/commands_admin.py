from __future__ import annotations
import discord
from discord import app_commands

from .state import State
from .observability import DiscordLogger


def register_admin_commands(tree: app_commands.CommandTree, state: State, logger: DiscordLogger, sync_fn, force_all_fn, settings):
    @tree.command(name="status", description="Status do Atlas v6 (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(interaction: discord.Interaction):
        await interaction.response.send_message(
            f"✅ Atlas v6 online\n"
            f"GUILD={settings.guild_id or 'GLOBAL'}\n"
            f"SYNC={settings.sync_commands}\n"
            f"LOG_LEVEL={settings.log_level}\n"
            f"DEBUG={state.debug_enabled}\n"
            f"AUTOTRADE_ENABLED={settings.autotrade_enabled}\n",
            ephemeral=True,
        )

    @tree.command(name="resync", description="Re-sincroniza comandos (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def resync(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await sync_fn()
        await interaction.followup.send("✅ Sync solicitado. Veja o canal de logs.", ephemeral=True)

    @tree.command(name="debug", description="Ativa/desativa logs detalhados (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def debug(interaction: discord.Interaction, enabled: bool):
        state.debug_enabled = bool(enabled)
        await logger.info(f"DEBUG set -> {state.debug_enabled} (by {interaction.user})")
        await interaction.response.send_message(f"🧪 DEBUG = {state.debug_enabled}", ephemeral=True)

    @tree.command(name="force_all", description="Força envio (teste) — Admin")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_all(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await force_all_fn()
        await interaction.followup.send(f"📨 ForceAll: {result}", ephemeral=True)

    @tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        await logger.error(f"Slash error: {error}")
