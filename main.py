# main.py
import os
import asyncio
import contextlib
import inspect
import signal
import discord
import pytz
import requests
from datetime import datetime
from discord.ext import tasks
from discord import app_commands

import config
import market
import news
import telegram
import signals  # ✅ novo

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Controle scheduler (para não disparar 2x no mesmo dia)
ultima_manha = None
ultima_tarde = None

# Rompimento
ULTIMO_PRECO = {}      # {ativo: preco}
FALHAS_SEGUIDAS = {}   # {ativo: count}

# Anti-overlap
PUBLICACAO_LOCK = asyncio.Lock()
SINAIS_LOCK = asyncio.Lock()

# Concorrência coleta mercado (seu market.py é sync; aqui continua com delay suave)
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

# Sync do tree (slash)
_TREE_SYNCED = False

# Shutdown robusto
_SHUTTING_DOWN = False
_FORCE_EXIT_ON_SIGNAL = True


# ─────────────────────────────
# Helpers
# ─────────────────────────────
async def _maybe_await(x):
    if inspect.isawaitable(x):
        return await x
    return x

def _get_cfg(name: str, default=None):
    return getattr(config, name, default)

def _channel_id(name: str):
    v = _get_cfg(name, 0)
    try:
        v = int(v)
        return v if v > 0 else None
    except Exception:
        return None


# ─────────────────────────────
# UTIL (embeds/strings)
# ─────────────────────────────
def emoji_var(v: float) -> str:
    if v is None:
        return "⏺️"
    if v > 0:
        return "🔼"
    if v < 0:
        return "🔽"
    return "⏺️"

def sentimento_geral(qtd_altas: int, qtd_quedas: int):
    if qtd_altas > qtd_quedas:
        return "😄 Mercado positivo", 0x2ECC71
    if qtd_quedas > qtd_altas:
        return "😨 Mercado defensivo", 0xE74C3C
    return "😐 Mercado neutro", 0xF1C40F

def texto_cenario(sent_label: str) -> str:
    if "positivo" in sent_label:
        return (
            "🧭 **Cenário:** apetite por risco maior.\n"
            "✅ Foque em qualidade e tendência.\n"
            "⚠️ Cuidado com euforia / alavancagem."
        )
    if "defensivo" in sent_label:
        return (
            "🧭 **Cenário:** aversão a risco.\n"
            "🛡️ Preserve capital e liquidez.\n"
            "🎯 Entradas só com confirmação."
        )
    return (
        "🧭 **Cenário:** mercado lateral/indefinido.\n"
        "🎯 Seletividade e exposição menor.\n"
        "⏳ Aguarde direção antes de aumentar mão."
    )

def ideias_em_baixa() -> str:
    return (
        "💡 **Dia de baixa (educacional):**\n"
        "• Prefira qualidade + caixa forte\n"
        "• ETFs amplos ajudam a diversificar\n"
        "• Aportes em etapas (não tudo de uma vez)\n"
        "• Evite decisões por impulso"
    )

async def log_bot(titulo: str, mensagem: str):
    canal = client.get_channel(_channel_id("CANAL_LOGS") or 0)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M"))
    await canal.send(embed=embed)

def dolar_para_real() -> float:
    try:
        r = requests.get(
            "https://api.exchangerate.host/latest?base=USD&symbols=BRL",
            timeout=10
        )
        data = r.json()
        rate = data.get("rates", {}).get("BRL")
        return float(rate) if rate else 5.0
    except Exception:
        return 5.0


# ─────────────────────────────
# ALERTA URGENTE (ROMPIMENTO)
# ─────────────────────────────
async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    canal = client.get_channel(_channel_id("CANAL_NOTICIAS") or 0)
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    limite = float(_get_cfg("LIMITE_ROMPIMENTO_PCT", 2.0))
    var = ((preco_atual - preco_antigo) / preco_antigo) * 100.0
    if abs(var) < limite:
        return

    direcao = "🚨🔼 ROMPIMENTO DE ALTA" if var > 0 else "🚨🔽 ROMPIMENTO DE BAIXA"
    cor = 0x2ECC71 if var > 0 else 0xE74C3C

    embed = discord.Embed(
        title=direcao,
        description=f"🧷 **Ativo:** `{ativo}`\n🏷️ **Categoria:** {categoria}",
        color=cor
    )
    embed.add_field(name="Preço anterior", value=f"{preco_antigo:,.4f}", inline=True)
    embed.add_field(name="Preço atual", value=f"{preco_atual:,.4f}", inline=True)
    embed.add_field(name="Movimento", value=f"{var:+.2f}% {emoji_var(var)}", inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))

    await canal.send(embed=embed)


# ─────────────────────────────
# COLETA (sequencial com delay leve — estável)
# ─────────────────────────────
async def coletar_lote(categoria: str, ativos: list[str], delay: float = 0.25):
    itens = []
    for ativo in ativos:
        try:
            p, v = market.dados_ativo(ativo)

            # FIIs: se preço não veio, não loga, só pula
            if ativo.endswith("11.SA") and p is None:
                await asyncio.sleep(delay)
                continue

            if p is None or v is None:
                FALHAS_SEGUIDAS[ativo] = FALHAS_SEGUIDAS.get(ativo, 0) + 1
                if FALHAS_SEGUIDAS[ativo] >= 3:
                    await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
                    FALHAS_SEGUIDAS[ativo] = 0
                await asyncio.sleep(delay)
                continue

            FALHAS_SEGUIDAS[ativo] = 0
            itens.append((ativo, float(p), float(v)))
            await alerta_rompimento(ativo, float(p), categoria)

        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo} ({categoria})\n{e}")

        await asyncio.sleep(delay)

    return itens

async def coletar_dados():
    dados = {}
    total = 0

    for categoria, ativos in config.ATIVOS.items():
        lote = await coletar_lote(categoria, ativos)
        if lote:
            dados[categoria] = lote
            total += len(lote)

    if total == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}

    return dados


# ─────────────────────────────
# EMBEDS (relatório + jornal)
# ─────────────────────────────
def embed_relatorio(dados: dict, cot: float):
    moves = [(a, p, v) for itens in dados.values() for (a, p, v) in itens]

    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, cor = sentimento_geral(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    embed = discord.Embed(
        title="📊 Relatório Completo do Mercado",
        description=f"**{sent_label}**\n\n{texto_cenario(sent_label)}",
        color=cor
    )

    embed.add_field(
        name="🔝 Top 3 Altas",
        value="\n".join([f"• `{a}` {emoji_var(v)} **{v:.2f}%**" for a, _, v in top_alta]) or "—",
        inline=False
    )
    embed.add_field(
        name="🔻 Top 3 Quedas",
        value="\n".join([f"• `{a}` {emoji_var(v)} **{v:.2f}%**" for a, _, v in top_baixa]) or "—",
        inline=False
    )

    for categoria, itens in dados.items():
        linhas = [
            f"• `{ativo}` {emoji_var(var)} **{var:.2f}%**  |  💲 {preco:,.2f}  |  🇧🇷 R$ {(preco*cot):,.2f}"
            for (ativo, preco, var) in itens
        ]
        embed.add_field(name=categoria, value="\n".join(linhas), inline=False)

    embed.add_field(name="💡 Dica do dia", value=ideias_em_baixa(), inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))
    return embed

def embed_jornal(manchetes: list[str], periodo: str):
    embed = discord.Embed(
        title=f"🗞️ Jornal do Mercado — {periodo}",
        description="🌍 Manchetes e impacto no mercado 😄",
        color=0x00BFFF
    )

    if not manchetes:
        embed.add_field(
            name="⚠️ Sem manchetes agora",
            value="O RSS retornou vazio. Tentaremos novamente no próximo ciclo.",
            inline=False
        )
        embed.set_footer(text="Fonte: Google News RSS")
        return embed

    bloco1 = "\n".join([f"📰 **{i}.** {m}" for i, m in enumerate(manchetes[:5], start=1)])
    bloco2 = "\n".join([f"🗞️ **{i}.** {m}" for i, m in enumerate(manchetes[5:10], start=6)])

    embed.add_field(name="🔥 Manchetes principais", value=bloco1, inline=False)
    if bloco2.strip():
        embed.add_field(name="📌 Mais notícias", value=bloco2, inline=False)

    embed.add_field(
        name="🧠 Leitura rápida",
        value="• Cenário macro (juros, inflação, dólar)\n• Gestão de risco sempre ✅",
        inline=False
    )
    embed.set_footer(text="Fonte: Google News RSS")
    return embed

def telegram_resumo(dados: dict, manchetes: list[str], periodo: str):
    moves = [(a, p, v) for itens in dados.values() for (a, p, v) in itens]
    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, _ = sentimento_geral(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    linhas = []
    linhas.append(f"📊 Resumo do Mercado — {periodo}")
    linhas.append(f"{sent_label}")
    linhas.append("")
    linhas.append(texto_cenario(sent_label))
    linhas.append("")
    linhas.append("🔝 Top 3 Altas")
    linhas.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_alta] or ["- —"])
    linhas.append("")
    linhas.append("🔻 Top 3 Quedas")
    linhas.extend([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_baixa] or ["- —"])
    linhas.append("")
    linhas.append("🌍 Manchetes do Mundo")
    if manchetes:
        for m in manchetes[:6]:
            linhas.append(f"📰 {m}")
    else:
        linhas.append("📰 (sem manchetes disponíveis agora)")
    linhas.append("")
    linhas.append(ideias_em_baixa())
    linhas.append("")
    linhas.append("— Atlas Finance")
    return "\n".join(linhas)


# ─────────────────────────────
# PUBLICAÇÕES (Relatório + Jornal + Telegram)
# ─────────────────────────────
async def enviar_publicacoes(periodo: str, *, enviar_tg=True):
    if PUBLICACAO_LOCK.locked():
        await log_bot("Scheduler", "Ignorado: execução já em andamento (anti-overlap).")
        return

    async with PUBLICACAO_LOCK:
        dados = await coletar_dados()
        if not dados:
            return

        cot = dolar_para_real()
        manchetes = await _maybe_await(news.noticias())

        canal_rel = client.get_channel(_channel_id("CANAL_ANALISE") or 0)
        canal_j = client.get_channel(_channel_id("CANAL_NOTICIAS") or 0)

        if canal_rel:
            await canal_rel.send(embed=embed_relatorio(dados, cot))
        else:
            await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise.")

        if canal_j and _get_cfg("NEWS_ATIVAS", True):
            await canal_j.send(embed=embed_jornal(manchetes, periodo))
        else:
            await log_bot("CANAL_NOTICIAS inválido", "Não encontrei canal de notícias ou NEWS_ATIVAS desativada.")

        if enviar_tg:
            ok = await _maybe_await(telegram.enviar_telegram(telegram_resumo(dados, manchetes, periodo)))
            if not ok:
                await log_bot("Telegram", "Falha ao enviar (token/chat_id).")

        if not manchetes:
            await log_bot("RSS vazio", "news.noticias() retornou lista vazia (pode ser temporário).")


# ─────────────────────────────
# SINAIS (SPOT + FUTURES) — novo
# ─────────────────────────────
def embed_sinais(itens: list[dict], titulo: str, timeframe: str):
    if not itens:
        return None

    # cor por “direção” predominante (bem simples)
    longs = sum(1 for s in itens if "LONG" in s.get("side", ""))
    shorts = sum(1 for s in itens if "SHORT" in s.get("side", ""))
    cor = 0x2ECC71 if longs > shorts else 0xE74C3C if shorts > longs else 0xF1C40F

    embed = discord.Embed(
        title=titulo,
        description=(
            f"⏱️ Timeframe: **{timeframe}**\n"
            "🧠 **Educacional** — use como *alerta*, não como certeza.\n"
            "⚠️ Sempre confirme no gráfico antes de operar."
        ),
        color=cor
    )

    linhas = []
    for s in itens[:12]:
        ex = s.get("exchange", "?").upper()
        sym = s.get("symbol", "?")
        kind = s.get("kind", "?")
        side = s.get("side", "?")
        price = s.get("price")
        rsi = s.get("rsi")
        vm = s.get("vol_mult")
        funding = s.get("funding")

        extra = []
        if rsi is not None:
            extra.append(f"RSI {rsi:.0f}")
        if vm is not None:
            extra.append(f"Vol×{vm:.1f}")
        if funding is not None:
            extra.append(f"Funding {funding*100:.3f}%")

        extra_txt = (" | " + " • ".join(extra)) if extra else ""
        linhas.append(f"• `{sym}` **{side}** ({kind}) — **{ex}** @ {price:,.4f}{extra_txt}")

    embed.add_field(name="📌 Sinais detectados", value="\n".join(linhas) if linhas else "—", inline=False)
    embed.set_footer(text=datetime.now(BR_TZ).strftime("Atualizado %d/%m/%Y %H:%M"))
    return embed

async def enviar_sinais(motivo: str = "auto"):
    if not _get_cfg("SINAIS_ATIVOS", False):
        return

    spot_id = _channel_id("CANAL_SINAIS_SPOT")
    fut_id = _channel_id("CANAL_SINAIS_FUTURES")
    if not spot_id or not fut_id:
        await log_bot("Sinais", "Canais não configurados (CANAL_SINAIS_SPOT / CANAL_SINAIS_FUTURES).")
        return

    if SINAIS_LOCK.locked():
        return

    async with SINAIS_LOCK:
        timeframe = _get_cfg("SINAIS_TIMEFRAME", "15m")
        pares = _get_cfg("SINAIS_PARES", [])
        exchanges = _get_cfg("SINAIS_EXCHANGES", ["binance"])
        cooldown = int(_get_cfg("SINAIS_COOLDOWN_MINUTES", 60))
        max_spot = int(_get_cfg("SINAIS_MAX_POR_CICLO_SPOT", 8))
        max_fut = int(_get_cfg("SINAIS_MAX_POR_CICLO_FUTURES", 8))

        # roda scan em thread (requests é sync)
        result = await asyncio.to_thread(
            signals.scan_signals,
            pares,
            timeframe,
            exchanges,
            cooldown,
            max_spot,
            max_fut,
        )

        spot = result.get("spot", [])
        fut = result.get("futures", [])
        errors = int(result.get("errors", 0))

        canal_spot = client.get_channel(spot_id)
        canal_fut = client.get_channel(fut_id)

        if spot and canal_spot:
            emb = embed_sinais(spot, f"📌 Sinais SPOT — {motivo}", timeframe)
            if emb:
                await canal_spot.send(embed=emb)

        if fut and canal_fut:
            emb = embed_sinais(fut, f"⚡ Sinais FUTURES — {motivo}", timeframe)
            if emb:
                await canal_fut.send(embed=emb)

        if errors:
            await log_bot("Sinais", f"Scan concluiu com {errors} erros (rate-limit/rede).")


@tasks.loop(minutes=5)
async def sinais_scheduler():
    # minutos vindo da config (ajustado no on_ready)
    await enviar_sinais("auto")


# ─────────────────────────────
# SLASH COMMANDS (admin)
# ─────────────────────────────
@tree.command(name="testetudo", description="Testa todas as publicações oficiais (Relatório + Jornal + Telegram) (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_testetudo(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await enviar_publicacoes("Teste Tudo (manual)", enviar_tg=True)
    await interaction.followup.send("✅ Disparei todas as publicações oficiais (Discord + Telegram).", ephemeral=True)

@tree.command(name="reiniciar", description="Reinicia o bot (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_reiniciar(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Reiniciando bot...", ephemeral=True)
    await asyncio.sleep(1)
    await shutdown("manual restart")

@tree.command(name="sinaisagora", description="Força um scan de sinais (SPOT + FUTURES) agora (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_sinaisagora(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    await enviar_sinais("manual")
    await interaction.followup.send("✅ Scan de sinais executado e postado nos canais.", ephemeral=True)

@tree.command(name="sinaisstatus", description="Mostra o status/config dos sinais (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_sinaisstatus(interaction: discord.Interaction):
    spot_id = _channel_id("CANAL_SINAIS_SPOT")
    fut_id = _channel_id("CANAL_SINAIS_FUTURES")
    msg = (
        f"**SINAIS_ATIVOS:** `{_get_cfg('SINAIS_ATIVOS', False)}`\n"
        f"**TIMEFRAME:** `{_get_cfg('SINAIS_TIMEFRAME', '15m')}`\n"
        f"**SCAN_MINUTES:** `{_get_cfg('SINAIS_SCAN_MINUTES', 5)}`\n"
        f"**EXCHANGES:** `{_get_cfg('SINAIS_EXCHANGES', ['binance'])}`\n"
        f"**PARES:** `{len(_get_cfg('SINAIS_PARES', []))}`\n"
        f"**CANAL_SPOT:** `{spot_id}`\n"
        f"**CANAL_FUTURES:** `{fut_id}`"
    )
    await interaction.response.send_message(msg, ephemeral=True)

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return
    await log_bot("Erro em slash command", str(error))


# ─────────────────────────────
# SCHEDULER (06h / 18h) — BRASIL
# ─────────────────────────────
@tasks.loop(minutes=1)
async def scheduler():
    global ultima_manha, ultima_tarde
    agora = datetime.now(BR_TZ)
    hhmm = agora.strftime("%H:%M")

    if hhmm == "06:00" and ultima_manha != agora.date():
        await enviar_publicacoes("Abertura (06:00)", enviar_tg=True)
        ultima_manha = agora.date()

    if hhmm == "18:00" and ultima_tarde != agora.date():
        await enviar_publicacoes("Fechamento (18:00)", enviar_tg=True)
        ultima_tarde = agora.date()


# ─────────────────────────────
# SHUTDOWN robusto
# ─────────────────────────────
async def shutdown(reason: str = "shutdown"):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True

    with contextlib.suppress(Exception):
        if scheduler.is_running():
            scheduler.cancel()
    with contextlib.suppress(Exception):
        if sinais_scheduler.is_running():
            sinais_scheduler.cancel()

    with contextlib.suppress(Exception):
        await log_bot("Shutdown", f"Encerrando... motivo: {reason}")

    with contextlib.suppress(Exception):
        await client.close()

    # Railway/containers às vezes precisam sair rápido
    if reason in ("SIGTERM", "SIGINT") and _FORCE_EXIT_ON_SIGNAL:
        os._exit(0)


def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _handler(sig_name: str):
        asyncio.create_task(shutdown(sig_name))
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig.name)


# ─────────────────────────────
# READY + SYNC
# ─────────────────────────────
@client.event
async def on_ready():
    global _TREE_SYNCED
    print(f"🤖 Conectado como {client.user}")

    # Sync controlado
    do_sync = os.getenv("SYNC_COMMANDS", "0").strip() == "1"
    if do_sync and not _TREE_SYNCED:
        try:
            gid = os.getenv("GUILD_ID")
            if gid:
                guild = discord.Object(id=int(gid))
                await tree.sync(guild=guild)
                print(f"✅ Slash commands sincronizados no servidor {gid}")
            else:
                await tree.sync()
                print("✅ Slash commands sincronizados globalmente")
            _TREE_SYNCED = True
        except Exception as e:
            print(f"⚠️ Falha ao sincronizar slash commands: {e}")

    if not scheduler.is_running():
        scheduler.start()

    # Ajusta intervalo do loop de sinais com base na config
    scan_min = int(_get_cfg("SINAIS_SCAN_MINUTES", 5))
    if scan_min < 1:
        scan_min = 1

    if _get_cfg("SINAIS_ATIVOS", False) and not sinais_scheduler.is_running():
        sinais_scheduler.change_interval(minutes=scan_min)
        sinais_scheduler.start()


# ─────────────────────────────
# ENTRYPOINT (mantém simples/estável)
# ─────────────────────────────
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    await client.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
