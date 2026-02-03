import os
import asyncio
import inspect
import signal
import contextlib
import logging
import discord
import pytz
import aiohttp
from datetime import datetime
from discord.ext import tasks
from discord import app_commands
from typing import Optional, Any, Dict, List, Tuple

import config
import market
import news
import telegram

import trading_signals as signals

TOKEN = os.getenv("DISCORD_TOKEN")
BR_TZ = pytz.timezone("America/Sao_Paulo")

# ─────────────────────────────
# LOGGING (reduz spam de aiohttp)
# ─────────────────────────────
logging.basicConfig(level=logging.INFO)
logging.getLogger("aiohttp.connector").setLevel(logging.CRITICAL)
logging.getLogger("aiohttp.client").setLevel(logging.CRITICAL)
logging.getLogger("aiohttp").setLevel(logging.CRITICAL)

# ─────────────────────────────
# DISCORD CLIENT (slash-only)
# ─────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ─────────────────────────────
# Globals
# ─────────────────────────────
HTTP: Optional[aiohttp.ClientSession] = None
_FX_CACHE = {"rate": 5.0, "ts": 0.0}
_FX_TTL = 600  # 10 min

PUBLICACAO_LOCK = asyncio.Lock()

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "8"))
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

ultima_manha = None
ultima_tarde = None

ULTIMO_PRECO: Dict[str, float] = {}
FALHAS_SEGUIDAS: Dict[str, int] = {}

_TREE_SYNCED = False
_SHUTTING_DOWN = False
_FORCE_EXIT = False
_FORCE_EXIT_ON_SIGNAL = True

# Sinais (não mexe no config.py)
SIGNALS_ENABLED = os.getenv("SIGNALS_ENABLED", "0").strip() == "1"
SIGNALS_CHANNEL_ID = int(os.getenv("SIGNALS_CHANNEL_ID", "0") or "0")  # se 0, não posta
SIGNALS_EVERY_MIN = int(os.getenv("SIGNALS_EVERY_MIN", "5") or "5")
SIGNALS_INTERVAL = os.getenv("SIGNALS_INTERVAL", "15m").strip()
SIGNALS_SYMBOLS = os.getenv("SIGNALS_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").strip()
SIGNALS_MARKETS = os.getenv("SIGNALS_MARKETS", "spot,futures").strip()
SIGNALS_COOLDOWN_MIN = int(os.getenv("SIGNALS_COOLDOWN_MIN", "60") or "60")

# ─────────────────────────────
# Helpers (sync/async compat)
# ─────────────────────────────
async def _maybe_await(x: Any):
    if inspect.isawaitable(x):
        return await x
    return x

async def _call_sync_or_async(fn, *args, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(lambda: fn(*args, **kwargs))

def _now_br() -> str:
    return datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

# ─────────────────────────────
# Util
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
    canal = client.get_channel(config.CANAL_LOGS)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=_now_br())
    await canal.send(embed=embed)

async def dolar_para_real_async() -> float:
    global _FX_CACHE, HTTP
    now = asyncio.get_event_loop().time()

    if (now - _FX_CACHE["ts"]) < _FX_TTL and _FX_CACHE["rate"] > 0:
        return float(_FX_CACHE["rate"])

    if HTTP is None:
        return float(_FX_CACHE.get("rate") or 5.0)

    url = "https://api.exchangerate.host/latest"
    params = {"base": "USD", "symbols": "BRL"}

    try:
        async with HTTP.get(url, params=params, timeout=10) as r:
            r.raise_for_status()
            data = await r.json()
            rate = data.get("rates", {}).get("BRL")
            rate = float(rate) if rate else 5.0
            _FX_CACHE = {"rate": rate, "ts": now}
            return rate
    except Exception:
        return float(_FX_CACHE.get("rate") or 5.0)

# ─────────────────────────────
# Shutdown
# ─────────────────────────────
async def _close_http():
    global HTTP
    if HTTP is not None:
        with contextlib.suppress(Exception):
            if not HTTP.closed:
                await HTTP.close()
    HTTP = None

async def shutdown(reason: str = "shutdown"):
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True

    with contextlib.suppress(Exception):
        if scheduler.is_running():
            scheduler.cancel()

    with contextlib.suppress(Exception):
        if signals_job.is_running():
            signals_job.cancel()

    with contextlib.suppress(Exception):
        await log_bot("Shutdown", f"Encerrando... motivo: {reason}")

    with contextlib.suppress(Exception):
        await asyncio.wait_for(_close_http(), timeout=5)

    with contextlib.suppress(Exception):
        await asyncio.wait_for(client.close(), timeout=8)

    if _FORCE_EXIT:
        os._exit(0)

def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _handler(sig_name: str):
        async def _go():
            global _FORCE_EXIT
            if _FORCE_EXIT_ON_SIGNAL:
                _FORCE_EXIT = True
            await shutdown(sig_name)
            if _FORCE_EXIT_ON_SIGNAL:
                os._exit(0)
        asyncio.create_task(_go())

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig.name)

# ─────────────────────────────
# Rompimento
# ─────────────────────────────
async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    canal = client.get_channel(config.CANAL_NOTICIAS)
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    limite = float(getattr(config, "LIMITE_ROMPIMENTO_PCT", 2.0))
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
    embed.set_footer(text=_now_br())

    await canal.send(embed=embed)

# ─────────────────────────────
# Coleta concorrente
# ─────────────────────────────
async def _dados_ativo_async(ativo: str):
    if not hasattr(market, "dados_ativo"):
        return None, None
    return await _call_sync_or_async(market.dados_ativo, ativo)

async def _fetch_one(categoria: str, ativo: str):
    async with SEM:
        try:
            p, v = await _dados_ativo_async(ativo)

            if ativo.endswith("11.SA") and p is None:
                return None

            if p is None or v is None:
                FALHAS_SEGUIDAS[ativo] = FALHAS_SEGUIDAS.get(ativo, 0) + 1
                if FALHAS_SEGUIDAS[ativo] >= 3:
                    await log_bot("Ativo sem dados", f"{ativo} ({categoria})")
                    FALHAS_SEGUIDAS[ativo] = 0
                return None

            FALHAS_SEGUIDAS[ativo] = 0
            await alerta_rompimento(ativo, float(p), categoria)
            return (ativo, float(p), float(v))

        except Exception as e:
            await log_bot("Erro ao buscar ativo", f"{ativo} ({categoria})\n{e}")
            return None

async def coletar_dados():
    coros = []
    order = []

    for categoria, ativos in config.ATIVOS.items():
        for ativo in ativos:
            coros.append(_fetch_one(categoria, ativo))
            order.append((categoria, ativo))

    results = await asyncio.gather(*coros, return_exceptions=False)

    dados = {}
    total = 0
    for (categoria, _), item in zip(order, results):
        if not item:
            continue
        dados.setdefault(categoria, []).append(item)
        total += 1

    if total == 0:
        await log_bot("Relatório cancelado", "Nenhum ativo retornou dados válidos.")
        return {}

    return dados

# ─────────────────────────────
# Embeds + Telegram
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
    embed.set_footer(text=_now_br())
    return embed

def embed_jornal(manchetes: list, periodo: str):
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

def telegram_resumo(dados: dict, manchetes: list, periodo: str):
    moves = [(a, p, v) for itens in dados.values() for (a, p, v) in itens]
    altas = sum(1 for _, _, v in moves if v > 0)
    quedas = sum(1 for _, _, v in moves if v < 0)
    sent_label, _ = sentimento_geral(altas, quedas)

    top_alta = sorted(moves, key=lambda x: x[2], reverse=True)[:3]
    top_baixa = sorted(moves, key=lambda x: x[2])[:3]

    linhas = [
        f"📊 Resumo do Mercado — {periodo}",
        f"{sent_label}",
        "",
        texto_cenario(sent_label),
        "",
        "🔝 Top 3 Altas",
        *([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_alta] or ["- —"]),
        "",
        "🔻 Top 3 Quedas",
        *([f"- {a} {emoji_var(v)} {v:.2f}%" for a, _, v in top_baixa] or ["- —"]),
        "",
        "🌍 Manchetes do Mundo",
    ]

    if manchetes:
        for m in manchetes[:6]:
            linhas.append(f"📰 {m}")
    else:
        linhas.append("📰 (sem manchetes disponíveis agora)")

    linhas += ["", ideias_em_baixa(), "", "— Atlas Finance"]
    return "\n".join(linhas)

# ─────────────────────────────
# Publicações (lock)
# ─────────────────────────────
async def enviar_publicacoes(periodo: str, *, enviar_tg=True):
    if PUBLICACAO_LOCK.locked():
        await log_bot("Scheduler", "Ignorado: execução já em andamento (anti-overlap).")
        return

    async with PUBLICACAO_LOCK:
        dados = await coletar_dados()
        if not dados:
            return

        cot = await dolar_para_real_async()
        manchetes = await _maybe_await(news.noticias())

        canal_rel = client.get_channel(config.CANAL_ANALISE)
        canal_j = client.get_channel(config.CANAL_NOTICIAS)

        if canal_rel:
            await canal_rel.send(embed=embed_relatorio(dados, cot))
        else:
            await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise.")

        if canal_j and getattr(config, "NEWS_ATIVAS", True):
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
# Trading Signals (educacional)
# ─────────────────────────────
def _signals_channel():
    if SIGNALS_CHANNEL_ID > 0:
        return client.get_channel(SIGNALS_CHANNEL_ID)
    return None

def _signals_settings():
    symbols = [s.strip().upper() for s in SIGNALS_SYMBOLS.split(",") if s.strip()]
    markets = [m.strip().lower() for m in SIGNALS_MARKETS.split(",") if m.strip()]
    if not markets:
        markets = ["spot"]
    return symbols, markets

def _signal_embed(sig: dict) -> discord.Embed:
    """
    sig: {symbol, market, interval, kind, message, rsi, ema_fast, ema_slow, price}
    """
    title = f"📈 Sinal (educacional) — {sig['symbol']} ({sig['market']})"
    color = 0x2ECC71 if sig.get("bias") == "LONG" else 0xE74C3C if sig.get("bias") == "SHORT" else 0xF1C40F

    e = discord.Embed(title=title, description=sig.get("message", ""), color=color)
    e.add_field(name="Timeframe", value=str(sig.get("interval", "?")), inline=True)
    e.add_field(name="Tipo", value=str(sig.get("kind", "?")), inline=True)
    e.add_field(name="Preço", value=str(sig.get("price", "—")), inline=True)

    if sig.get("rsi") is not None:
        e.add_field(name="RSI", value=f"{sig['rsi']:.1f}", inline=True)
    if sig.get("ema_fast") is not None and sig.get("ema_slow") is not None:
        e.add_field(name="EMA20/EMA50", value=f"{sig['ema_fast']:.4f} / {sig['ema_slow']:.4f}", inline=True)

    if sig.get("invalidation"):
        e.add_field(name="Invalidação (referência)", value=str(sig["invalidation"]), inline=False)

    e.set_footer(text=f"{_now_br()} • Paper/Educacional • Não é recomendação")
    return e

async def _run_signals_once(label: str = "auto"):
    if not SIGNALS_ENABLED:
        return
    chan = _signals_channel()
    if not chan:
        # não crasha: só loga
        await log_bot("Signals", "SIGNALS_ENABLED=1 mas SIGNALS_CHANNEL_ID não definido.")
        return

    symbols, markets = _signals_settings()

    try:
        out: List[dict] = await signals.scan(
            symbols=symbols,
            markets=markets,
            interval=SIGNALS_INTERVAL,
            cooldown_min=SIGNALS_COOLDOWN_MIN,
        )
        if not out:
            return

        # manda no máximo 5 por ciclo pra evitar flood
        for sig in out[:5]:
            await chan.send(embed=_signal_embed(sig))

    except Exception as e:
        await log_bot("Signals", f"Falha ao rodar sinais ({label}): {e}")

# ─────────────────────────────
# READY + SYNC
# ─────────────────────────────
@client.event
async def on_ready():
    global HTTP, _TREE_SYNCED
    print(f"🤖 Conectado como {client.user}")

    if HTTP is None:
        timeout = aiohttp.ClientTimeout(total=12, connect=3, sock_read=8)
        connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENCY, ttl_dns_cache=300, enable_cleanup_closed=True)
        HTTP = aiohttp.ClientSession(timeout=timeout, connector=connector)

        # injeta sessão se tiver set_session (não quebra se não existir)
        for mod in (market, news, telegram):
            if hasattr(mod, "set_session"):
                with contextlib.suppress(Exception):
                    mod.set_session(HTTP)

        # sinais usam aiohttp
        signals.set_session(HTTP)

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

    if SIGNALS_ENABLED and not signals_job.is_running():
        signals_job.start()

# ─────────────────────────────
# Slash commands (mínimo: mantém antigos + 1 para testar sinais)
# ─────────────────────────────
@tree.command(name="testetudo", description="Testa publicações oficiais (Relatório + Jornal + Telegram) (Admin)")
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
    global _FORCE_EXIT
    _FORCE_EXIT = True
    await shutdown("manual restart")

@tree.command(name="sinaisagora", description="Roda uma varredura de sinais agora (educacional) (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_sinaisagora(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if not SIGNALS_ENABLED:
        await interaction.followup.send("⚠️ Sinais estão desligados. Sete SIGNALS_ENABLED=1 no Railway.", ephemeral=True)
        return
    await _run_signals_once("manual")
    await interaction.followup.send("✅ Varredura de sinais executada.", ephemeral=True)

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
# Scheduler 06/18 (mercado)
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
# Job sinais
# ─────────────────────────────
@tasks.loop(minutes=1)
async def signals_job():
    # roda a cada 1 min, mas dispara só quando bater o intervalo configurado
    # (evita drift; simples e estável)
    if not SIGNALS_ENABLED:
        return
    agora = datetime.now(BR_TZ)
    if (agora.minute % max(1, SIGNALS_EVERY_MIN)) != 0:
        return
    await _run_signals_once("auto")

# ─────────────────────────────
# Entry point robusto
# ─────────────────────────────
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")

    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    try:
        async with client:
            await client.start(TOKEN)
    finally:
        with contextlib.suppress(Exception):
            await _close_http()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
