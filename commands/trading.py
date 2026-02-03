# commands/trading.py
import os
import uuid
import discord
from datetime import datetime
from discord import app_commands
import pytz

BR_TZ = pytz.timezone("America/Sao_Paulo")


def _mention_channel(ch_id: int) -> str:
    return f"<#{ch_id}>"


def _calc_r_multiple(side: str, entry: float, stop: float, exit_price: float):
    risk = abs(entry - stop)
    if risk <= 0:
        return None

    side = (side or "").upper()
    if side == "SHORT":
        return (entry - exit_price) / risk
    return (exit_price - entry) / risk  # LONG default


def register_trading_commands(tree: app_commands.CommandTree, store, client: discord.Client):
    """
    Registra comandos de trading:
      - /nova_entrada
      - /fechar_trade
      - /stats
    store: SheetsStore ou None
    """

    async def _ensure_store(interaction: discord.Interaction) -> bool:
        if store is None:
            await interaction.response.send_message(
                "❌ Sheets não configurado. Falta `GOOGLE_SHEET_ID` e/ou `GOOGLE_SA_B64` no Railway.",
                ephemeral=True
            )
            return False
        return True

    def _get_trading_channel_id() -> int:
        v = os.getenv("CANAL_TRADING")
        return int(v) if v else 0

    @tree.command(name="nova_entrada", description="Cria uma entrada no canal de trading e registra no Sheets (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        asset="Ex: BTC-USD, AAPL, PETR4.SA",
        side="LONG ou SHORT",
        timeframe="Ex: 15m, 1h, 4h, 1d",
        entry="Preço de entrada (ou zona central)",
        stop="Stop (invalidação)",
        tp1="Alvo 1 (opcional)",
        tp2="Alvo 2 (opcional)",
        notes="Motivo/observação (opcional)"
    )
    async def nova_entrada(
        interaction: discord.Interaction,
        asset: str,
        side: str,
        timeframe: str,
        entry: float,
        stop: float,
        tp1: float = 0.0,
        tp2: float = 0.0,
        notes: str = ""
    ):
        if not await _ensure_store(interaction):
            return

        trading_channel_id = _get_trading_channel_id()
        if trading_channel_id <= 0:
            await interaction.response.send_message(
                "❌ `CANAL_TRADING` não configurado no Railway.",
                ephemeral=True
            )
            return

        await store.ensure_tab()

        trade_id = f"ATL-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(BR_TZ)

        ch = client.get_channel(trading_channel_id)
        if ch is None:
            await interaction.response.send_message(
                f"❌ Não encontrei o canal {trading_channel_id}.",
                ephemeral=True
            )
            return

        side_u = (side or "").upper()
        color = 0x2ECC71 if side_u == "LONG" else 0xE74C3C

        embed = discord.Embed(
            title=f"🧠 Nova Entrada — {asset} ({side_u})",
            description=f"🆔 `{trade_id}`\n⏱️ **TF:** {timeframe}\n📍 **Status:** OPEN",
            color=color
        )
        embed.add_field(name="Entrada", value=f"{entry:,.6f}", inline=True)
        embed.add_field(name="Stop", value=f"{stop:,.6f}", inline=True)

        if tp1 and tp1 > 0:
            embed.add_field(name="TP1", value=f"{tp1:,.6f}", inline=True)
        if tp2 and tp2 > 0:
            embed.add_field(name="TP2", value=f"{tp2:,.6f}", inline=True)

        if notes.strip():
            embed.add_field(name="Notas", value=notes[:900], inline=False)

        embed.set_footer(text=now.strftime("%d/%m/%Y %H:%M (BR)"))
        msg = await ch.send(embed=embed)

        row = [
            trade_id,
            now.isoformat(),
            str(interaction.user.id),
            str(trading_channel_id),
            str(msg.id),
            asset,
            side_u,
            timeframe,
            entry,
            stop,
            tp1 if tp1 and tp1 > 0 else "",
            tp2 if tp2 and tp2 > 0 else "",
            "OPEN",
            "",
            "",
            "",
            "",
            "",
            notes or ""
        ]

        ok = await store.append_trade(row)
        if not ok:
            await interaction.response.send_message("⚠️ Entrada criada, mas falhou ao salvar no Sheets.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Entrada criada em {_mention_channel(trading_channel_id)} com ID `{trade_id}`.",
            ephemeral=True
        )

    @tree.command(name="fechar_trade", description="Fecha uma entrada (GREEN/RED/BE) e registra no Sheets (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        trade_id="ID do trade (ATL-XXXXXXXX)",
        outcome="GREEN ou RED ou BE",
        exit_price="Preço de saída (opcional, para calcular R)",
        notes="Observação final (opcional)"
    )
    async def fechar_trade(
        interaction: discord.Interaction,
        trade_id: str,
        outcome: str,
        exit_price: float = 0.0,
        notes: str = ""
    ):
        if not await _ensure_store(interaction):
            return

        outcome_u = (outcome or "").upper()
        if outcome_u not in ("GREEN", "RED", "BE"):
            await interaction.response.send_message("❌ outcome precisa ser GREEN, RED ou BE.", ephemeral=True)
            return

        row_idx, header, row = await store.find_trade_row(trade_id)
        if not row_idx:
            await interaction.response.send_message("❌ Trade não encontrado no Sheets.", ephemeral=True)
            return

        row = row + [""] * (len(header) - len(row))
        col = {name: i for i, name in enumerate(header)}

        status = (row[col.get("status", 12)] or "").upper()
        if status == "CLOSED":
            await interaction.response.send_message("⚠️ Esse trade já está fechado.", ephemeral=True)
            return

        asset = row[col.get("asset", 5)]
        side = row[col.get("side", 6)]
        timeframe = row[col.get("timeframe", 7)]

        entry = float(row[col.get("entry", 8)] or 0)
        stop = float(row[col.get("stop", 9)] or 0)

        r_mult = None
        exit_val = None
        if exit_price and exit_price > 0:
            exit_val = float(exit_price)
            r_mult = _calc_r_multiple(side, entry, stop, exit_val)

        now = datetime.now(BR_TZ)

        existing_notes = row[col.get("notes", 18)] if "notes" in col else ""
        final_notes = notes.strip() if notes.strip() else (existing_notes or "")

        updates = {
            "status": "CLOSED",
            "closed_at": now.isoformat(),
            "closed_by": str(interaction.user.id),
            "outcome": outcome_u,
            "exit_price": (exit_val if exit_val is not None else ""),
            "r_multiple": (round(r_mult, 2) if r_mult is not None else ""),
            "notes": final_notes
        }

        ok = await store.update_trade_by_id(trade_id, updates)
        if not ok:
            await interaction.response.send_message("❌ Falha ao atualizar o Sheets.", ephemeral=True)
            return

        # postar resultado no canal
        try:
            trading_channel_id = int(row[col.get("channel_id", 3)] or 0)
            message_id = int(row[col.get("message_id", 4)] or 0)
        except Exception:
            trading_channel_id, message_id = 0, 0

        ch = client.get_channel(trading_channel_id) if trading_channel_id else None

        color = 0x2ECC71 if outcome_u == "GREEN" else (0xE74C3C if outcome_u == "RED" else 0xF1C40F)
        icon = "✅" if outcome_u == "GREEN" else ("🛑" if outcome_u == "RED" else "⚖️")

        emb = discord.Embed(
            title=f"{icon} Fechamento — {asset} ({side})",
            description=f"🆔 `{trade_id}`\n⏱️ **TF:** {timeframe}\n📍 **Status:** CLOSED",
            color=color
        )
        emb.add_field(name="Outcome", value=outcome_u, inline=True)
        if exit_val is not None:
            emb.add_field(name="Saída", value=f"{exit_val:,.6f}", inline=True)
        if r_mult is not None:
            emb.add_field(name="Resultado (R)", value=f"{r_mult:+.2f}R", inline=True)
        if final_notes:
            emb.add_field(name="Notas", value=final_notes[:900], inline=False)
        emb.set_footer(text=now.strftime("%d/%m/%Y %H:%M (BR)"))

        if ch:
            await ch.send(embed=emb)

            # tenta editar msg original (não é obrigatório)
            if message_id:
                try:
                    msg = await ch.fetch_message(message_id)
                    if msg.embeds:
                        e0 = msg.embeds[0]
                        e0_new = discord.Embed.from_dict(e0.to_dict())
                        e0_new.description = (e0_new.description or "") + f"\n\n✅ **Fechado:** {outcome_u}"
                        await msg.edit(embed=e0_new)
                except Exception:
                    pass

        await interaction.response.send_message("✅ Trade fechado e registrado.", ephemeral=True)

    @tree.command(name="stats", description="Resumo de performance baseado no Sheets (Admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(days="Período em dias (ex: 7, 30, 90)")
    async def stats(interaction: discord.Interaction, days: int = 30):
        if not await _ensure_store(interaction):
            return

        values = await store.get_all_trades()
        if not values or len(values) < 2:
            await interaction.response.send_message("⚠️ Sem trades registrados ainda.", ephemeral=True)
            return

        header = values[0]
        col = {name: i for i, name in enumerate(header)}

        now = datetime.now(BR_TZ)
        cutoff = now.timestamp() - (days * 86400)

        total = 0
        wins = 0
        losses = 0
        be = 0
        r_sum = 0.0
        r_count = 0

        for row in values[1:]:
            row = row + [""] * (len(header) - len(row))
            status = (row[col.get("status", 12)] or "").upper()
            if status != "CLOSED":
                continue

            closed_at = row[col.get("closed_at", 13)] or ""
            try:
                ts = datetime.fromisoformat(closed_at).timestamp()
            except Exception:
                ts = None

            if ts is not None and ts < cutoff:
                continue

            outcome = (row[col.get("outcome", 15)] or "").upper()
            total += 1
            if outcome == "GREEN":
                wins += 1
            elif outcome == "RED":
                losses += 1
            else:
                be += 1

            r = row[col.get("r_multiple", 17)] or ""
            try:
                r_val = float(r)
                r_sum += r_val
                r_count += 1
            except Exception:
                pass

        if total == 0:
            await interaction.response.send_message(f"⚠️ Sem trades fechados nos últimos {days} dias.", ephemeral=True)
            return

        winrate = (wins / total) * 100.0
        avg_r = (r_sum / r_count) if r_count else None

        msg = (
            f"📈 **Stats ({days}d)**\n"
            f"• Trades fechados: **{total}**\n"
            f"• GREEN: **{wins}** | RED: **{losses}** | BE: **{be}**\n"
            f"• Winrate: **{winrate:.1f}%**\n"
        )
        if avg_r is not None:
            msg += f"• Avg R (onde informado): **{avg_r:+.2f}R**\n"
        else:
            msg += "• Avg R: **—** (informe `exit_price` ao fechar)\n"

        await interaction.response.send_message(msg, ephemeral=True)
