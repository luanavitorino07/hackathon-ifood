"""Compras de supermercado: lista de itens e agendamento, por regras (reserva da IA do Intérprete).

A lista é uma sequência de itens ("arroz 5kg, 2 leites, café"); cada um vira uma busca no iFood com
`merchant_type=GROCERIES`. O agendamento ("todo sábado às 10h") é guardado no nosso sistema: o iFood não
recebe agendamento (o MCP liberado só busca). Na data, a cesta é refeita com os preços do dia e o
cliente confirma antes de qualquer compra.

Datas: guardadas em UTC; interpretadas e mostradas no horário de Brasília (UTC-3, sem horário de verão).
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

LOCAL_TZ = timezone(timedelta(hours=-3), "BRT")
MAX_LIST_ITEMS = 12
MIN_LEAD = timedelta(minutes=30)  # agendamento precisa de folga para montar a cesta
MAX_AHEAD = timedelta(days=120)
DEFAULT_HOUR = 10
RECURRENCES = ("none", "weekly", "biweekly", "monthly")
RECURRENCE_LABELS = {"none": "", "weekly": "toda semana", "biweekly": "a cada 15 dias", "monthly": "todo mês"}
_WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_WEEKDAY_LABELS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
            "sete": 7, "oito": 8, "nove": 9, "dez": 10, "doze": 12, "meia": 6}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _fold(text: str) -> str:
    """Como `_plain`, mas caractere a caractere (mesmo comprimento): permite recuperar o acento depois."""
    return "".join((_plain(ch) or "?")[:1] for ch in text.lower())


def _accented(name: str, folded: str, original: str) -> str:
    """'feijao' -> 'feijão', recuperando a grafia da mensagem original."""
    idx = folded.find(name)
    return original[idx:idx + len(name)] if idx >= 0 else name


@dataclass(frozen=True)
class ListItem:
    name: str  # o que buscar ("arroz", "leite integral")
    quantity: int = 1  # unidades/pacotes pedidos
    note: str | None = None  # tamanho/peso pedido ("5 kg", "2 litros"): a IA escolhe a embalagem

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "quantity": self.quantity, "note": self.note}

    @classmethod
    def from_dict(cls, data: Any) -> "ListItem | None":
        if not isinstance(data, dict):
            return None
        name, qty, note = data.get("name"), data.get("quantity"), data.get("note")
        name = clean_name(name) if isinstance(name, str) else None
        if not name:
            return None
        qty = qty if isinstance(qty, int) and not isinstance(qty, bool) and 1 <= qty <= 50 else 1
        return cls(name, qty, note.strip()[:30] if isinstance(note, str) and note.strip() else None)

    def label(self) -> str:
        if self.note:
            return f"{self.name} ({self.note})"
        return f"{self.quantity}x {self.name}" if self.quantity > 1 else self.name


@dataclass(frozen=True)
class ScheduleRequest:
    """O que o cliente pediu de agendamento. `when` None = quer agendar, mas falta dizer quando."""

    when: datetime | None  # UTC
    recurrence: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {"when": iso(self.when) if self.when else None, "recurrence": self.recurrence}

    @classmethod
    def from_dict(cls, data: Any) -> "ScheduleRequest | None":
        if not isinstance(data, dict):
            return None
        rec = data.get("recurrence") if data.get("recurrence") in RECURRENCES else "none"
        return cls(parse_iso(data.get("when")), rec)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc)


def describe_when(moment: datetime, recurrence: str = "none") -> str:
    """'sábado, 25/10 às 10h00 (toda semana)' no horário de Brasília."""
    local = moment.astimezone(LOCAL_TZ)
    text = f"{_WEEKDAY_LABELS[local.weekday()]}, {local:%d/%m} às {local:%H}h{local:%M}"
    label = RECURRENCE_LABELS.get(recurrence, "")
    return f"{text} ({label})" if label else text


def now_label(now: datetime) -> str:
    """Data/hora atual para o prompt da IA (ela precisa saber o que é 'amanhã' e 'sábado')."""
    local = now.astimezone(LOCAL_TZ)
    return f"{_WEEKDAY_LABELS[local.weekday()]}, {local:%Y-%m-%d %H:%M} (horário de Brasília)"


def next_occurrence(moment: datetime, recurrence: str) -> datetime | None:
    if recurrence == "weekly":
        return moment + timedelta(days=7)
    if recurrence == "biweekly":
        return moment + timedelta(days=14)
    if recurrence == "monthly":
        local = moment.astimezone(LOCAL_TZ)
        year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        day = min(local.day, calendar.monthrange(year, month)[1])
        return local.replace(year=year, month=month, day=day).astimezone(timezone.utc)
    return None


def schedule_problem(when: datetime, now: datetime) -> str | None:
    """Motivo para recusar o horário, ou None se ele serve."""
    if when < now + MIN_LEAD:
        return "Esse horário já passou ou está muito em cima (preciso de pelo menos 30 minutos)."
    if when > now + MAX_AHEAD:
        return "Consigo agendar com até 4 meses de antecedência."
    return None


def local_moment(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), LOCAL_TZ).astimezone(timezone.utc)


# ---- detecção por regras ------------------------------------------------------------
_GROCERY = re.compile(r"\b(supermercados?|mercados?|mercadinho|lista de compras?|compras? do mes|"
                      r"compras? da semana|compras? de mercado|rancho|hortifruti|sacolao)\b")
_SCHEDULE_WORD = re.compile(r"\b(agend\w*|program\w*|marca\w* para|toda (semana|segunda|terca|quarta|quinta|sexta)|"
                            r"todo (mes|sabado|domingo|dia)|todas as \w+s|semanal\w*|quinzena\w*|mensal\w*|a cada)\b")
_DAY_WORD = re.compile(r"\b(amanha|depois de amanha|(segunda|terca|quarta|quinta|sexta|sabado|domingo)(-feira)?|"
                       r"dia \d{1,2}|\d{1,2}/\d{1,2})\b")
_TIME = re.compile(r"\b(?:as |a |ate )?(\d{1,2})(?:h|:|hs)(\d{2})?\b|\bao meio[- ]dia\b")
_NO_SCHEDULE = re.compile(r"\b(sem agendar|nao (precisa|quero) agendar|sem agendamento|pra agora|para agora|"
                          r"agora mesmo|cancela\w* o agendamento)\b")
_ADD = re.compile(r"^(?:e\s+)?(?:adiciona|adicione|acrescenta|acrescente|inclui|inclua|coloca|coloque|poe|ponha|"
                  r"bota|bote|mais|tambem)\b\s*(.*)$")
_REMOVE = re.compile(r"^(?:tira|tire|remove|remova|retira|retire|exclui|exclua)\b\s*(.*)$")
_LIST_SCHEDULES = re.compile(r"\b(meus agendamentos|minhas compras agendadas|meu agendamento|"
                             r"o que (esta|tem|ta) agendado|quais (sao os )?agendamentos)\b")
_CANCEL_SCHEDULE = re.compile(r"\b(cancela\w*|desmarca\w*|apaga\w*|remove\w*)\b.*\bagend\w*|"
                              r"\bnao quero mais\b.*\bagend\w*")
# palavras de abertura/ligação que não são itens
_FILLER = re.compile(r"^(?:(?:quero|queria|gostaria de|preciso(?: de)?|vou precisar de|fazer|faz|fa[cz]a|"
                     r"monta|monte|comprar|ir|uma|um|a|o|as|os|minha|meu|compra|compras|lista|de|do|da|no|na|pro|"
                     r"pra|para|com|itens?|seguinte|tipo|so|e|agendar|agenda|agende)(?:\s+|$))+")
_UNITS_WEIGHT = r"kg|kgs|quilos?|g|gramas?|l|litros?|ml|lts?"
_UNITS_PACK = r"pacotes?|pct|latas?|caixas?|cx|garrafas?|unidades?|un|und|potes?|sacos?|bandejas?|duzias?|dz|rolos?|fardos?"
_QTY = re.compile(rf"^(\d+(?:[.,]\d+)?|{'|'.join(_NUMBERS)})\s*({_UNITS_WEIGHT}|{_UNITS_PACK})?\b\s*(?:de\s+)?(.*)$")
_TRAILING_SIZE = re.compile(rf"^(.*?)\s+(\d+(?:[.,]\d+)?)\s*({_UNITS_WEIGHT}|{_UNITS_PACK})$")


def wants_groceries(text: str) -> bool:
    return bool(_GROCERY.search(_plain(text)))


def wants_schedule(text: str) -> bool:
    plain = _plain(text)
    today_at = re.search(r"\bhoje\b", plain) and _TIME.search(plain)  # "hoje às 18h"; "mercado hoje" é agora
    return bool(_SCHEDULE_WORD.search(plain) or _DAY_WORD.search(plain) or today_at)


def drops_schedule(text: str) -> bool:
    return bool(_NO_SCHEDULE.search(_plain(text)))


def wants_schedule_list(text: str) -> bool:
    return bool(_LIST_SCHEDULES.search(_plain(text)))


def wants_schedule_cancel(text: str) -> bool:
    return bool(_CANCEL_SCHEDULE.search(_plain(text)))


_TRAILING_WORDS = {"de", "do", "da", "dos", "das", "no", "na", "pro", "pra", "para", "e", "com", "o", "a"}


def _singular(word: str) -> str:
    """'feijões' -> 'feijão', 'pães' -> 'pão', 'leites' -> 'leite' (busca e correspondência no singular)."""
    for plural, single in (("ões", "ão"), ("ães", "ão"), ("oes", "ao"), ("aes", "ao")):
        if word.endswith(plural) and len(word) >= 4:
            return word[:-len(plural)] + single
    if word.endswith("s") and not word.endswith(("ss", "is", "us")) and len(word) > 4:
        return word[:-1]
    return word


def clean_name(text: str, singular: bool = True) -> str | None:
    words = [_singular(w) if singular else w for w in re.findall(r"[^\W\d_]+", text.lower())]
    while words and words[-1] in _TRAILING_WORDS:
        words.pop()
    while words and words[0] in _TRAILING_WORDS:
        words.pop(0)
    return " ".join(words) if 1 <= len(words) <= 4 and len("".join(words)) >= 2 else None


def _strip_schedule(text: str) -> str:
    """Tira do texto as expressões de data/horário/recorrência para sobrar só a lista."""
    for pattern in (_SCHEDULE_WORD, _DAY_WORD, _TIME, _NO_SCHEDULE, _GROCERY):
        text = pattern.sub(" ", text)
    return re.sub(r"\b(as|a|ate|para|pra|no|na|de manha|a tarde|a noite|toda|todo|e)\s*$", " ", text)


def _item(chunk: str) -> ListItem | None:
    chunk = _FILLER.sub("", chunk.strip(" .!?-")).strip()
    m = _QTY.match(chunk)
    qty, note = 1, None
    if m and m.group(3):
        raw, unit, chunk = m.group(1), m.group(2), m.group(3)
        number = _NUMBERS.get(raw) or float(raw.replace(",", "."))
        if unit and re.fullmatch(_UNITS_WEIGHT, unit):
            note = f"{raw} {unit}"
        elif unit and unit.startswith(("duzia", "dz")):
            n = max(1, int(number))
            note = f"{n} dúzia" + ("s" if n > 1 else "")
        else:
            qty = max(1, min(50, int(number)))
    else:
        t = _TRAILING_SIZE.match(chunk)  # "arroz 5kg"
        if t:
            chunk, note = t.group(1), f"{t.group(2)} {t.group(3)}"
    name = clean_name(_FILLER.sub("", chunk.strip()), singular=False)  # singular depois de recuperar o acento
    return ListItem(name, qty, note) if name else None


def parse_items(text: str) -> tuple[ListItem, ...]:
    """Itens de uma lista em texto livre: 'arroz 5kg, 2 leites, café e 1 dúzia de ovos'."""
    original, folded = text.lower(), _fold(text)
    plain = folded
    if ":" in plain:
        plain = plain.split(":", 1)[1]
    plain = _strip_schedule(plain)
    chunks = re.split(r"[,;\n]|\s+e\s+|\s+mais\s+", plain)
    items: dict[str, ListItem] = {}
    for chunk in chunks:
        item = _item(chunk)
        if item and item.name not in items:
            name = clean_name(_accented(item.name, folded, original)) or item.name
            items[item.name] = ListItem(name, item.quantity, item.note)
    return tuple(items.values())[:MAX_LIST_ITEMS]


def edit_items(text: str, current: tuple[ListItem, ...]) -> tuple[ListItem, ...] | None:
    """'adiciona café' / 'tira o leite'; None se a mensagem não edita a lista."""
    original = text.lower().strip()
    plain = _fold(original)
    add, remove = _ADD.match(plain), _REMOVE.match(plain)
    if add:
        new = parse_items(original[add.start(1):])
        names = {i.name for i in current}
        return (current + tuple(i for i in new if i.name not in names))[:MAX_LIST_ITEMS]
    if remove:
        gone = {_plain(i.name) for i in parse_items(original[remove.start(1):])}
        return tuple(i for i in current if not any(g in _plain(i.name) or _plain(i.name) in g for g in gone))
    return None


def parse_schedule(text: str, now: datetime) -> ScheduleRequest | None:
    """Agendamento pedido na mensagem (regras). None se a mensagem não fala de agendar."""
    plain = _plain(text)
    if drops_schedule(plain) or not wants_schedule(plain):
        return None
    recurrence = ("biweekly" if re.search(r"quinzen|a cada (15|quinze) dias|a cada duas semanas", plain) else
                  "monthly" if re.search(r"todo mes|mensal|todo dia \d|a cada mes", plain) else
                  "weekly" if re.search(r"toda semana|semanal|toda (segunda|terca|quarta|quinta|sexta)|"
                                        r"todo (sabado|domingo)|todas as \w+s|a cada semana", plain) else "none")
    local_now = now.astimezone(LOCAL_TZ)
    today = local_now.date()
    day: date | None = None
    if "depois de amanha" in plain:
        day = today + timedelta(days=2)
    elif re.search(r"\bamanha\b", plain):
        day = today + timedelta(days=1)
    elif re.search(r"\bhoje\b", plain):
        day = today
    else:
        dm = re.search(r"\b(\d{1,2})/(\d{1,2})\b", plain)
        dd = re.search(r"\bdia (\d{1,2})\b", plain)
        wd = next((i for i, w in enumerate(_WEEKDAYS) if re.search(rf"\b{w}\b", plain)), None)
        try:
            if dm:
                day = date(today.year, int(dm.group(2)), int(dm.group(1)))
                if day < today:
                    day = day.replace(year=today.year + 1)
            elif dd:
                n = int(dd.group(1))
                year, month = (today.year, today.month) if n >= today.day else (
                    (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1))
                day = date(year, month, n)
            elif wd is not None:
                day = today + timedelta(days=(wd - today.weekday()) % 7 or 7)
        except ValueError:
            day = None
    hour, minute = DEFAULT_HOUR, 0
    t = _TIME.search(plain)
    if t and t.group(1):
        hour, minute = int(t.group(1)), int(t.group(2) or 0)
    elif t:
        hour = 12
    elif "de manha" in plain:
        hour = 9
    elif "a tarde" in plain:
        hour = 15
    elif "a noite" in plain:
        hour = 19
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = DEFAULT_HOUR, 0
    if day is None:
        return ScheduleRequest(None, recurrence)
    when = local_moment(day, hour, minute)
    if day == today and when < now and not t:  # "hoje" sem horário e já passou das 10h: próxima hora cheia
        when = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return ScheduleRequest(when, recurrence)


def schedule_from_ai(value: Any, now: datetime) -> ScheduleRequest | None:
    """Agendamento devolvido pela IA ({quer_agendar, data, hora, recorrencia}); None se não pediu."""
    if not isinstance(value, dict) or value.get("quer_agendar") is not True:
        return None
    recurrence = {"nenhuma": "none", "semanal": "weekly", "quinzenal": "biweekly",
                  "mensal": "monthly"}.get(value.get("recorrencia"), "none")
    raw_day, raw_time = value.get("data"), value.get("hora")
    try:
        day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else None
    except ValueError:
        day = None
    if day is None:
        return ScheduleRequest(None, recurrence)
    hour, minute = DEFAULT_HOUR, 0
    if isinstance(raw_time, str):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw_time.strip())
        if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
            hour, minute = int(m.group(1)), int(m.group(2))
    return ScheduleRequest(local_moment(day, hour, minute), recurrence)


def items_from_ai(value: Any) -> tuple[ListItem, ...]:
    """Lista devolvida pela IA ([{item, quantidade, detalhe}]), validada."""
    out: dict[str, ListItem] = {}
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("item"), str):
            continue
        item = ListItem.from_dict({"name": raw["item"], "quantity": raw.get("quantidade"),
                                   "note": raw.get("detalhe")})
        if item and item.name not in out:
            out[item.name] = item
    return tuple(out.values())[:MAX_LIST_ITEMS]


def list_text(items: tuple[ListItem, ...] | list[ListItem]) -> str:
    return ", ".join(i.label() for i in items)
