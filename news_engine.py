from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Set, Tuple, Optional
import re
import html
import os

import discord
import pytz
import feedparser

import config

BR_TZ = pytz.timezone("America/Sao_Paulo")


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)                 # corrige &#224; etc
    text = re.sub(r"<[^>]+>", " ", text)       # remove tags HTML
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _short(text: str, n: int) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str
    key: str  # pra dedupe


class OfflineTranslator:
    """
    Tradução sem API:
    - Se Argos Translate estiver disponível + modelo instalado -> tradução real offline.
    - Se não -> fallback por glossário/frases (parcial, mas estável).
    """
    def __init__(self):
        self.mode = "glossary"
        self._argos_translate = None
        self._argos_ready = False

        # tenta ativar Argos
        try:
            import argostranslate.translate as atranslate
            import argostranslate.package as apackage

            self._argos_translate = atranslate
            self._apackage = apackage
            self._argos_ready = self._has_en_pt_installed()

            # se não tiver instalado, tenta instalar de um arquivo local (opcional)
            if not self._argos_ready:
                self._try_install_local_model()
                self._argos_ready = self._has_en_pt_installed()

            if self._argos_ready:
                self.mode = "argos"
        except Exception:
            self.mode = "glossary"

        # glossário (fallback) — focado em cripto/mercado
        self.phrases = [
            (r"\bprice\b", "preço"),
            (r"\bprices\b", "preços"),
            (r"\bmarket\b", "mercado"),
            (r"\bmarkets\b", "mercados"),
            (r"\binvestor(s)?\b", "investidor\\1"),
            (r"\banalyst(s)?\b", "analista\\1"),
            (r"\bexchange\b", "corretora"),
            (r"\bexchanges\b", "corretoras"),
            (r"\bregulation\b", "regulamentação"),
            (r"\bbill\b", "projeto de lei"),
            (r"\bapproval\b", "aprovação"),
            (r"\bSEC\b", "SEC"),
            (r"\bETF\b", "ETF"),
            (r"\bspot\b", "spot"),
            (r"\bfutures\b", "futuros"),
            (r"\brally\b", "alta forte"),
            (r"\bsurge\b", "dispara"),
            (r"\bplunge\b", "despenca"),
            (r"\bdump\b", "queda forte"),
            (r"\bcrash\b", "queda brusca"),
            (r"\bfalls?\b", "cai"),
            (r"\bdrops?\b", "cai"),
            (r"\brises?\b", "sobe"),
            (r"\bgains?\b", "ganha"),
            (r"\bloss(es)?\b", "perda\\1"),
            (r"\bover(s)?old\b", "sobrevendido"),
            (r"\boverbought\b", "sobrecomprado"),
            (r"\bfear\b", "medo"),
            (r"\bcapitulation\b", "capitulação"),
            (r"\bwhale(s)?\b", "baleia\\1"),
            (r"\bon-chain\b", "on-chain"),
            (r"\bhashrate\b", "hashrate"),
            (r"\bmining\b", "mineração"),
            (r"\bto exit\b", "sair de"),
            (r"\breduce staff\b", "reduzir equipe"),
            (r"\bfocus on\b", "focar em"),
            (r"\baccording to\b", "segundo"),
            (r"\bcould\b", "pode"),
            (r"\bmay\b", "pode"),
            (r"\bnear\b", "perto de"),
            (r"\blikely\b", "provável"),
            (r"\bindicator\b", "indicador"),
            (r"\bdata\b", "dados"),
        ]

    def _has_en_pt_installed(self) -> bool:
        try:
            langs = self._argos_translate.get_installed_languages()
            en = next((l for l in langs if l.code == "en"), None)
            pt = next((l for l in langs if l.code in ("pt", "pt_br", "pt-BR", "pt_BR")), None)
            if not en or not pt:
                return False
            tr = en.get_translation(pt)
            return tr is not None
        except Exception:
            return False

    def _try_install_local_model(self):
        """
        Opcional: se você colocar um modelo Argos no repo, ele instala automaticamente.
        Caminho esperado: ./models/en_pt.argosmodel
        """
        try:
            path = os.path.join(os.getcwd(), "models", "en_pt.argosmodel")
            if not os.path.exists(path):
                return
            pkg = self._apackage.Package.load_from_path(path)
            self._apackage.install_from_path(path)
        except Exception:
            pass

    def translate_en_to_pt(self, text: str) -> Tuple[str, bool]:
        text = (text or "").strip()
        if not text:
            return "", (self.mode == "argos")

        if self.mode == "argos" and self._argos_ready:
            try:
                return self._argos_translate.translate(text, "en", "pt"), True
            except Exception:
                # cai no fallback
                pass

        # fallback glossário (parcial)
        out = text

        # preserva tickers/proper nouns simples: tokens ALLCAPS 2-8 não mexe (BTC, XRP, SEC)
        # (ainda assim, replacements por regex são benignos)
        for pat, rep in self.phrases:
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)

        return out, False


class NewsEngine:
    def __init__(self):
        self.seen: Set[str] = set()
        self.tr = OfflineTranslator()

    def _feeds_en(self) -> List[Tuple[str, str]]:
        feeds = getattr(config, "NEWS_RSS_FEEDS_EN", None)
        if feeds:
            return list(feeds)
        return list(getattr(config, "NEWS_RSS_FEEDS", []))

    def _max_items(self) -> int:
        if hasattr(config, "NEWS_MAX_ITEMS_EACH"):
            return int(getattr(config, "NEWS_MAX_ITEMS_EACH"))
        return int(getattr(config, "NEWS_MAX_ITEMS", 6))

    def fetch(self) -> Tuple[List[NewsItem], List[NewsItem], List[str], bool]:
        """
        Retorna:
          pt_items (tradução da MESMA lista EN)
          en_items
          sources
          translated_ok (True se Argos traduziu de fato; False se fallback)
        """
        en_items: List[NewsItem] = []
        max_items = self._max_items()

        for source, url in self._feeds_en():
            d = feedparser.parse(url)
            for entry in (d.entries or [])[:10]:
                title = _clean_text((entry.get("title") or "").strip())
                summary = _clean_text((entry.get("summary") or entry.get("description") or "").strip())
                link = (entry.get("link") or "").strip()

                if not title:
                    continue

                key = f"{source}|{link or title}".lower()
                if key in self.seen:
                    continue

                en_items.append(
                    NewsItem(
                        source=source,
                        title=_short(title, 140),
                        summary=_short(summary, 240),
                        key=key,
                    )
                )

                if len(en_items) >= max_items:
                    break
            if len(en_items) >= max_items:
                break

        sources = []
        for it in en_items:
            if it.source not in sources:
                sources.append(it.source)

        # traduz item-a-item pra garantir “mesma notícia”
        pt_items: List[NewsItem] = []
        translated_ok_any = True  # só fica True se Argos estiver realmente traduzindo
        for it in en_items:
            block = f"{it.title} — {it.summary}" if it.summary else it.title
            pt_block, ok = self.tr.translate_en_to_pt(block)
            if not ok:
                translated_ok_any = False

            if " — " in pt_block:
                pt_title, pt_sum = pt_block.split(" — ", 1)
            else:
                pt_title, pt_sum = pt_block, ""

            pt_items.append(
                NewsItem(
                    source=it.source,
                    title=_short(_clean_text(pt_title), 140),
                    summary=_short(_clean_text(pt_sum), 240),
                    key=it.key,
                )
            )

        return pt_items, en_items, sources, translated_ok_any

    def mark_seen(self, en_items: List[NewsItem]):
        for it in en_items:
            self.seen.add(it.key)

    def build_embed(self, pt: List[NewsItem], en: List[NewsItem], sources: List[str], translated_ok: bool) -> discord.Embed:
        now = datetime.now(BR_TZ)
        e = discord.Embed(
            title="📰 Atlas Newsletter — Cripto (PT/EN)",
            description="Texto direto (sem link). Fontes no final apenas para referência.\n🧠 Educacional — não é recomendação financeira.",
            color=0xF1C40F,
        )

        if not en:
            e.add_field(name="🇧🇷 Português", value="📭 Sem novidades relevantes neste ciclo.", inline=False)
            e.add_field(name="🇺🇸 English", value="📭 No relevant updates this cycle.", inline=False)
        else:
            # MAIS ESPAÇADO: 1 item por bloco + linha em branco
            pt_blocks = []
            en_blocks = []

            for i in range(len(en)):
                en_it = en[i]
                pt_it = pt[i] if i < len(pt) else None

                en_txt = f"{i+1}) **{en_it.title}**"
                if en_it.summary:
                    en_txt += f"\n{en_it.summary}"
                en_blocks.append(en_txt)

                if pt_it:
                    pt_txt = f"{i+1}) **{pt_it.title}**"
                    if pt_it.summary:
                        pt_txt += f"\n{pt_it.summary}"
                else:
                    pt_txt = en_txt
                pt_blocks.append(pt_txt)

            e.add_field(name="🇧🇷 Português", value=_short("\n\n".join(pt_blocks), 1024), inline=False)
            e.add_field(name="🇺🇸 English", value=_short("\n\n".join(en_blocks), 1024), inline=False)

            if not translated_ok:
                e.add_field(
                    name="ℹ️ Tradução",
                    value="Modo offline sem API: usando fallback parcial (glossário). Para tradução perfeita, instale modelo Argos (offline).",
                    inline=False,
                )

        if sources:
            e.add_field(name="📎 Fontes (referência)", value="; ".join(sources), inline=False)

        inv = getattr(config, "DISCORD_INVITE_LINK", "").strip()
        if inv and "COLE_AQUI" not in inv:
            e.add_field(name="🚀 Tempo real no Discord", value=f"Entre na Atlas Community: {inv}", inline=False)

        e.set_footer(text=f"{now.strftime('%d/%m/%Y %H:%M')} BRT")
        return e
