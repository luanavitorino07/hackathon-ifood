"""RAG mínimo: busca por palavras-chave em documentos Markdown da empresa (sem banco vetorial).

Cada documento é dividido em seções `## ...`. Uma seção pode declarar `topics: a, b, c` e um bloco
```params com linhas `chave: valor` (valores inteiros viram `int`), devolvido em `KnowledgeHit.data`.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.agents.ports import KnowledgeHit

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "um", "uma",
    "para", "por", "com", "sem", "que", "se", "ou", "ao", "aos", "the", "and", "mais", "menos", "nunca",
    "sempre", "quando", "como", "ser", "sobre", "antes", "apos", "entre", "ja", "nao", "sim",
}
_PARAMS = re.compile(r"```params\s*\n(.*?)```", re.S)


def _tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return [t for t in re.findall(r"[a-z0-9]+", plain) if len(t) > 2 and t not in _STOPWORDS]


def _stem(token: str) -> str:
    for suffix in ("coes", "cao", "mente", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def _terms(text: str) -> list[str]:
    return [_stem(t) for t in _tokens(text)]


@dataclass
class _Chunk:
    document_id: str
    title: str
    section: str
    text: str
    topics: set[str] = field(default_factory=set)
    data: dict[str, Any] = field(default_factory=dict)
    terms: list[str] = field(default_factory=list)


def _parse_params(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = (p.strip() for p in line.split(":", 1))
            data[key] = int(value) if re.fullmatch(r"-?\d+", value) else value
    return data


def _load(path: Path) -> list[_Chunk]:
    raw = path.read_text(encoding="utf-8")
    title_match = re.search(r"^# (.+)$", raw, re.M)
    title = title_match.group(1).strip() if title_match else path.stem
    chunks = []
    for part in re.split(r"^## ", raw, flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        topics_match = re.search(r"^topics:\s*(.+)$", body, re.M)
        topics = {_stem(t) for t in _tokens(topics_match.group(1))} if topics_match else set()
        params = _PARAMS.search(body)
        text = re.sub(r"^topics:.*$", "", _PARAMS.sub("", body), flags=re.M).strip()
        chunks.append(_Chunk(path.stem, title, heading.strip(), text, topics,
                             _parse_params(params.group(1)) if params else {},
                             _terms(heading + " " + text) + list(topics)))
    return chunks


class MarkdownKnowledgeBase:
    """Implementa `KnowledgePort`. Os documentos são da empresa (compartilhados), não por cliente."""

    def __init__(self, directory: Path | str = KNOWLEDGE_DIR) -> None:
        self._chunks = [c for p in sorted(Path(directory).glob("*.md")) for c in _load(p)]
        n = max(len(self._chunks), 1)
        df: dict[str, int] = {}
        for c in self._chunks:
            for t in set(c.terms):
                df[t] = df.get(t, 0) + 1
        self._idf = {t: math.log(1 + n / d) for t, d in df.items()}

    def search(self, tenant_id: str, query: str, topics: tuple[str, ...] = (), k: int = 3) -> list[KnowledgeHit]:
        del tenant_id  # base única de demonstração; isolamento por empresa entra com documentos reais
        q = set(_terms(query))
        wanted = {_stem(t) for topic in topics for t in _tokens(topic)}
        scored = []
        for c in self._chunks:
            score = sum(self._idf.get(t, 0) * c.terms.count(t) for t in q)
            score += 2.0 * len(wanted & c.topics)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda sc: -sc[0])
        return [KnowledgeHit(c.document_id, c.title, f"{c.section}: {c.text[:400]}", round(s, 3), dict(c.data))
                for s, c in scored[:k]]
