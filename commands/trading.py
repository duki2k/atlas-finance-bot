import os
import uuid
import discord
from datetime import datetime
from discord import app_commands
from typing import Optional

import config


def _now_br():
    # datetime naive ok, só para texto
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return None


def _calc_r(side: str, entry: float, stop: float, exit_price: float) -> Optional[float]:
    """
    R = (resultado) / (risco)
    LONG: (exit-entry)/(entry-stop)
    SHORT: (entry-exit)/(stop-entry)
    """
    if entry is None or stop is None or exit_price is None:
        return None

    risk_long = entry - stop
    risk_short = stop - entry
    if side == "LONG":
        if risk_long == 0:
            return None
        return (exit_price - entry) / risk_long
    else:
        if risk_short == 0:
            return None
        return (entry - exit_price) / risk_short


def _require_trading_channel(interaction: discord.Interaction) -> bool:
    only = getattr(config, "TRADING_CHANNEL_ONLY", True)
    chan_id = getattr(config, "TRADING_CHANNEL_ID", 0)
    if not only or not chan_id:
        return True
    return interaction.channel_id == int(chan_id)


def register_trading_commands(tree: app_commands.CommandTree, store, client: discord.Client):
    enabled = getattr(config, "TRADING_ENABLED", True)

    if not enabled:
        return

    @tree.command(name="tradeabrir", description="Registra um trade (paper/educacional) (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        asset="Ex: BTCUSDT, AAPL, PETR4.SA",
        side="LONG ou SHORT",
        timeframe="Ex: 5m, 15m, 1h, 4h, 1d",
        entry="Preço de entrada",
        stop="Stop",
        tp1="Alvo 1 (opcional)",
        tp2="Alvo 2 (opcional)",
        notes="Observações (opcional)",
    )
    async def tradeabrir(
        interaction: discord.Interaction,
        asset: str,
        side: str,
        timeframe: str,
        entry: str,
        stop: str,
        tp1: Optional[str] = None,
        tp2: Optional[str] = None,
        notes: Optional[str] = None,
    ):
        if not _require_trading_channel(interaction):
            await interaction.response.send_message("⚠️ Use este comando apenas no canal de trading.", ephemeral=True)
            return

        side = side.upper().strip()
        if side not in ("LONG", "SHORT"):
            await interaction.response.send_message("❌ side deve ser LONG ou SHORT.", ephemeral=True)
            return

        f_entry = _parse_float(entry)
        f_stop = _parse_float(stop)
        f_tp1 = _parse_float(tp1) if tp1 else None
        f_tp2 = _parse_float(tp2) if tp2 else None

        if f_entry is None or f_stop is None:
            await interaction.response.send_message("❌ entry e stop precisam ser números válidos.", ephemeral=True)
            return

        trade_id = uuid.uuid4().hex[:8].upper()

        embed = discord.Embed(
            title="📌 Trade Registrado (Paper/Educacional)",
            description=f"🆔 **ID:** `{trade_id}`\n⏱️ **Horário:** {_now_br()}",
            color=0x5865F2
        )
        embed.add_field(name="Ativo", value=f"`{asset.upper()}`", inline=True)
        embed.add_field(name="Lado", value=f"**{side}**", inline=True)
        embed.add_field(name="Timeframe", value=f"`{timeframe}`", inline=True)
        embed.add_field(name="Entrada", value=f"{f_entry}", inline=True)
        embed.add_field(name="Stop", value=f"{f_stop}", inline=True)
        embed.add_field(name="TP1", value=f"{f_tp1}" if f_tp1 is not None else "—", inline=True)
        embed.add_field(name="TP2", value=f"{f_tp2}" if f_tp2 is not None else "—", inline=True)
        if notes:
            embed.add_field(name="Notas", value=notes[:900], inline=False)

        embed.set_footer(text="⚠️ Conteúdo educacional/paper. Não é recomendação de investimento.")

        await interaction.response.defer(thinking=True, ephemeral=True)

        chan_id = int(getattr(config, "TRADING_CHANNEL_ID", interaction.channel_id))
        channel = client.get_channel(chan_id) or interaction.channel

        msg = await channel.send(embed=embed)

        row = {
            "trade_id": trade_id,
            "created_at": _now_br(),
            "created_by": str(interaction.user.id),
            "channel_id": str(channel.id),
            "message_id": str(msg.id),
            "asset": asset.upper(),
            "side": side,
            "timeframe": timeframe,
            "entry": f_entry,
            "stop": f_stop,
            "tp1": f_tp1 if f_tp1 is not None else "",
            "tp2": f_tp2 if f_tp2 is not None else "",
            "status": "OPEN",
            "notes": notes or "",
        }

        ok = await store.append_trade(row) if hasattr(store, "append_trade") else False
        if not ok and getattr(store, "enabled", lambda: False)():
            await interaction.followup.send("⚠️ Trade registrado no Discord, mas falhou ao salvar no Sheets.", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Trade registrado com ID `{trade_id}`.", ephemeral=True)

    @tree.command(name="tradefechar", description="Fecha um trade e marca GREEN/RED/BE (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        trade_id="ID do trade",
        outcome="GREEN / RED / BE",
        exit_price="Preço de saída",
        notes="Notas finais (opcional)",
    )
    async def tradefechar(
        interaction: discord.Interaction,
        trade_id: str,
        outcome: str,
        exit_price: str,
        notes: Optional[str] = None,
    ):
        if not _require_trading_channel(interaction):
            await interaction.response.send_message("⚠️ Use este comando apenas no canal de trading.", ephemeral=True)
            return

        outcome = outcome.upper().strip()
        if outcome not in ("GREEN", "RED", "BE"):
            await interaction.response.send_message("❌ outcome deve ser GREEN, RED ou BE.", ephemeral=True)
            return

        f_exit = _parse_float(exit_price)
        if f_exit is None:
            await interaction.response.send_message("❌ exit_price precisa ser número válido.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        # Para calcular R, vamos tentar pegar o trade OPEN mais recente (se store suportar listagem)
        side = None
        entry = None
        stop = None

        if hasattr(store, "list_trades"):
            opens = await store.list_trades(status="OPEN", limit=200)
            for t in opens:
                if str(t.get("trade_id", "")).upper() == trade_id.upper():
                    side = str(t.get("side", "")).upper()
                    entry = _parse_float(t.get("entry", ""))
                    stop = _parse_float(t.get("stop", ""))
                    break

        r_val = _calc_r(side or "LONG", entry, stop, f_exit) if entry is not None and stop is not None else None
        r_str = f"{r_val:.3f}" if r_val is not None else ""

        ok = await store.close_trade(
            trade_id=trade_id.upper(),
            closed_at=_now_br(),
            closed_by=str(interaction.user.id),
            outcome=outcome,
            exit_price=str(f_exit),
            r_multiple=r_str,
            notes=(notes or ""),
        ) if hasattr(store, "close_trade") else False

        if not ok:
            await interaction.followup.send("❌ Não consegui fechar no Sheets. Confere se o ID existe e está OPEN.", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Trade `{trade_id.upper()}` fechado como **{outcome}**. R={r_str or '—'}", ephemeral=True)

    @tree.command(name="trades", description="Lista trades OPEN (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def trades(interaction: discord.Interaction):
        if not _require_trading_channel(interaction):
            await interaction.response.send_message("⚠️ Use este comando apenas no canal de trading.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        if not hasattr(store, "list_trades"):
            await interaction.followup.send("❌ Storage não suporta listagem.", ephemeral=True)
            return

        items = await store.list_trades(status="OPEN", limit=15)
        if not items:
            await interaction.followup.send("📭 Nenhum trade OPEN no momento.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Trades OPEN", color=0x00BFFF)
        for t in items[:15]:
            embed.add_field(
                name=f"🆔 {t.get('trade_id','')}",
                value=(
                    f"**{t.get('asset','')}** | {t.get('side','')} | {t.get('timeframe','')}\n"
                    f"Entrada: {t.get('entry','')} | Stop: {t.get('stop','')}"
                ),
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="tradestats", description="Estatísticas rápidas (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def tradestats(interaction: discord.Interaction):
        if not _require_trading_channel(interaction):
            await interaction.response.send_message("⚠️ Use este comando apenas no canal de trading.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        if not hasattr(store, "list_trades"):
            await interaction.followup.send("❌ Storage não suporta estatística.", ephemeral=True)
            return

        closed = await store.list_trades(status="CLOSED", limit=200)
        open_ = await store.list_trades(status="OPEN", limit=200)

        total = len(closed)
        greens = sum(1 for t in closed if str(t.get("outcome", "")).upper() == "GREEN")
        reds = sum(1 for t in closed if str(t.get("outcome", "")).upper() == "RED")
        bes = sum(1 for t in closed if str(t.get("outcome", "")).upper() == "BE")

        rs = []
        for t in closed:
            r = _parse_float(t.get("r_multiple", ""))
            if r is not None:
                rs.append(r)

        winrate = (greens / total * 100.0) if total else 0.0
        avg_r = (sum(rs) / len(rs)) if rs else 0.0

        embed = discord.Embed(title="📈 Trading Stats (rápido)", color=0x2ECC71 if winrate >= 50 else 0xE74C3C)
        embed.add_field(name="OPEN", value=str(len(open_)), inline=True)
        embed.add_field(name="CLOSED", value=str(total), inline=True)
        embed.add_field(name="Winrate", value=f"{winrate:.1f}%", inline=True)
        embed.add_field(name="GREEN / RED / BE", value=f"{greens} / {reds} / {bes}", inline=False)
        embed.add_field(name="Média de R", value=f"{avg_r:.3f}" if rs else "—", inline=True)
        embed.set_footer(text="⚠️ Paper/educacional. Use gestão de risco.")

        await interaction.followup.send(embed=embed, ephemeral=True)
