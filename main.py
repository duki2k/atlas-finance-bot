# main.py
import os
import asyncio
import contextlib
import signal
import inspect
import discord
import pytz
from datetime import datetime
from discord.ext import tasks
from discord import app_commands
from typing import Optional, Any, Dict, List, Tuple

import config
import market
import news
import telegram

# ─────────────────────────────
# ENV
# ─────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
BR_TZ = pytz.timezone("America/Sao_Paulo")

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "6") or "6")
SEM = asyncio.Semaphore(MAX_CONCURRENCY)

SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "0").strip() == "1"
GUILD_ID = os.getenv("GUILD_ID", "").strip()

# ─────────────────────────────
# DISCORD (Slash-only)
# ─────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ─────────────────────────────
# STATE
# ─────────────────────────────
PUBLICACAO_LOCK = asyncio.Lock()

ultima_manha = None
ultima_tarde = None

ULTIMO_PRECO: Dict[str, float] = {}
FALHAS_SEGUIDAS: Dict[str, int] = {}

_TREE_SYNCED = False
_SHUTTING_DOWN = False
_FORCE_EXIT = False  # usado no /reiniciar para Railway religar

# FX cache (USD->BRL)
_FX_CACHE = {"rate": 5.0, "ts": 0.0}
_FX_TTL = 600  # 10 min


# ─────────────────────────────
# Helpers: sync/async compat
# ─────────────────────────────
async def _call_sync_or_async(fn, *args, **kwargs):
    """Permite chamar função sync (em thread) ou async (await)."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(lambda: fn(*args, **kwargs))

def _now_br() -> str:
    return datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")


# ─────────────────────────────
# Util / Embeds
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

def _get_cfg_int(name: str, default: int = 0) -> int:
    return int(getattr(config, name, default) or default)

def _get_cfg_bool(name: str, default: bool = True) -> bool:
    v = getattr(config, name, default)
    return bool(v)

def _get_cfg_float(name: str, default: float = 2.0) -> float:
    try:
        return float(getattr(config, name, default))
    except Exception:
        return default

async def log_bot(titulo: str, mensagem: str):
    canal_logs = _get_cfg_int("CANAL_LOGS", 0)
    if canal_logs <= 0:
        return
    canal = client.get_channel(canal_logs)
    if not canal:
        return
    embed = discord.Embed(title=f"📋 {titulo}", description=mensagem, color=0xE67E22)
    embed.set_footer(text=_now_br())
    await canal.send(embed=embed)


# ─────────────────────────────
# FX (USD->BRL) (em thread, com cache)
# ─────────────────────────────
def _dolar_para_real_sync() -> float:
    import requests
    r = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=BRL", timeout=10)
    data = r.json()
    rate = data.get("rates", {}).get("BRL")
    return float(rate) if rate else 5.0

async def dolar_para_real_async() -> float:
    now = asyncio.get_event_loop().time()
    if (now - _FX_CACHE["ts"]) < _FX_TTL and _FX_CACHE["rate"] > 0:
        return float(_FX_CACHE["rate"])

    try:
        rate = await asyncio.to_thread(_dolar_para_real_sync)
        _FX_CACHE["rate"] = float(rate)
        _FX_CACHE["ts"] = now
        return float(rate)
    except Exception:
        return float(_FX_CACHE.get("rate") or 5.0)


# ─────────────────────────────
# Rompimento (automático)
# ─────────────────────────────
async def alerta_rompimento(ativo: str, preco_atual: float, categoria: str):
    canal_id = _get_cfg_int("CANAL_NOTICIAS", 0)
    if canal_id <= 0:
        return
    canal = client.get_channel(canal_id)
    if not canal:
        return

    preco_antigo = ULTIMO_PRECO.get(ativo)
    ULTIMO_PRECO[ativo] = preco_atual

    if preco_antigo is None or preco_antigo <= 0:
        return

    limite = _get_cfg_float("LIMITE_ROMPIMENTO_PCT", 2.0)
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
# Coleta concorrente (market.py é sync -> roda em thread)
# ─────────────────────────────
async def _fetch_one(categoria: str, ativo: str):
    async with SEM:
        try:
            p, v = await _call_sync_or_async(market.dados_ativo, ativo)

            # FIIs: se preço não veio, ignora sem log
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
    coros: List[Any] = []
    order: List[Tuple[str, str]] = []

    ativos_map = getattr(config, "ATIVOS", {})
    if not isinstance(ativos_map, dict) or not ativos_map:
        await log_bot("Config", "ATIVOS não definido ou vazio no config.py.")
        return {}

    for categoria, ativos in ativos_map.items():
        for ativo in ativos:
            coros.append(_fetch_one(categoria, ativo))
            order.append((categoria, ativo))

    results = await asyncio.gather(*coros, return_exceptions=False)

    dados: Dict[str, List[Tuple[str, float, float]]] = {}
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
# Embeds (Relatório + Jornal)
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
        embed.add_field(name=str(categoria), value="\n".join(linhas), inline=False)

    embed.add_field(name="💡 Dica do dia", value=ideias_em_baixa(), inline=False)
    embed.set_footer(text=f"Atualizado {_now_br()}")
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
# Publicações (anti-overlap)
# ─────────────────────────────
async def enviar_publicacoes(periodo: str, *, enviar_tg: bool = True):
    if PUBLICACAO_LOCK.locked():
        await log_bot("Scheduler", "Ignorado: execução já em andamento (anti-overlap).")
        return

    async with PUBLICACAO_LOCK:
        dados = await coletar_dados()
        if not dados:
            return

        cot = await dolar_para_real_async()
        manchetes = await _call_sync_or_async(news.noticias)

        canal_rel_id = _get_cfg_int("CANAL_ANALISE", 0)
        canal_j_id = _get_cfg_int("CANAL_NOTICIAS", 0)

        canal_rel = client.get_channel(canal_rel_id) if canal_rel_id > 0 else None
        canal_j = client.get_channel(canal_j_id) if canal_j_id > 0 else None

        if canal_rel:
            await canal_rel.send(embed=embed_relatorio(dados, cot))
        else:
            await log_bot("CANAL_ANALISE inválido", "Não encontrei canal de análise (ID errado?).")

        if canal_j and _get_cfg_bool("NEWS_ATIVAS", True):
            await canal_j.send(embed=embed_jornal(manchetes, periodo))
        else:
            await log_bot("CANAL_NOTICIAS inválido", "Não encontrei canal de notícias ou NEWS_ATIVAS desativada.")

        if enviar_tg:
            try:
                ok = await _call_sync_or_async(telegram.enviar_telegram, telegram_resumo(dados, manchetes, periodo))
                if not ok:
                    await log_bot("Telegram", "Falha ao enviar (verifique TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID).")
            except Exception as e:
                await log_bot("Telegram", f"Erro ao enviar: {e}")

        if not manchetes:
            await log_bot("RSS vazio", "news.noticias() retornou lista vazia (pode ser temporário).")


# ─────────────────────────────
# Slash Commands (somente 2)
# ─────────────────────────────
@tree.command(name="testetudo", description="Testa publicações oficiais (Relatório + Jornal + Telegram) (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_testetudo(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await enviar_publicacoes("Teste Tudo (manual)", enviar_tg=True)
    await interaction.followup.send("✅ Disparei todas as publicações (Discord + Telegram).", ephemeral=True)

@tree.command(name="reiniciar", description="Reinicia o bot (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def slash_reiniciar(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Reiniciando bot...", ephemeral=True)
    await asyncio.sleep(1)
    global _FORCE_EXIT
    _FORCE_EXIT = True
    await shutdown("manual restart")

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
# Scheduler 06/18 BR
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
# Shutdown + Signals
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
        await log_bot("Shutdown", f"Encerrando... motivo: {reason}")

    with contextlib.suppress(Exception):
        await client.close()

    if _FORCE_EXIT:
        os._exit(0)

def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    def _handler(sig_name: str):
        async def _go():
            global _FORCE_EXIT
            _FORCE_EXIT = True
            await shutdown(sig_name)
            os._exit(0)
        asyncio.create_task(_go())

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handler, sig.name)


# ─────────────────────────────
# Ready + Sync
# ─────────────────────────────
@client.event
async def on_ready():
    global _TREE_SYNCED
    print(f"🤖 Conectado como {client.user}")

    # Sincroniza slash commands quando você quiser
    if SYNC_COMMANDS and not _TREE_SYNCED:
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                await tree.sync(guild=guild)
                print(f"✅ Slash commands sincronizados no servidor {GUILD_ID}")
            else:
                await tree.sync()
                print("✅ Slash commands sincronizados globalmente")
            _TREE_SYNCED = True
        except Exception as e:
            print(f"⚠️ Falha ao sincronizar slash commands: {e}")

    if not scheduler.is_running():
        scheduler.start()


# ─────────────────────────────
# Entry point robusto
# ─────────────────────────────
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN não definido.")
    loop = asyncio.get_running_loop()
    install_signal_handlers(loop)

    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
