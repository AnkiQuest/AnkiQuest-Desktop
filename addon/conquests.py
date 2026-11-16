"""Native conquest data and local-only label suggestions."""

import html
import re

from . import deck_names, language, share

_HIDDEN = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>|<!--.*?-->", re.I | re.S)
_SOUND = re.compile(r"\[(?:sound|anki:play):[^\]]*\]")
_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.S)
_ID = re.compile(r"[A-Za-z]{0,4}[-_.#]?\d+(?:[-_.:/]?[A-Za-z]{0,2}\d+)*[A-Za-z]?")
_HEX = re.compile(r"[0-9A-Fa-f]{8,}(?:-[0-9A-Fa-f]{4,})*")
_TAG = re.compile(r"\{\{([^{}]*)\}\}")
_PLACEHOLDER = re.compile(r"\[\[type:[\s\S]*?(?:\]\]|$)|\{\{[\s\S]*?(?:\}\}|$)")
_SPECIAL = {"Tags", "Type", "Deck", "Subdeck", "CardFlag", "Card", "FrontSide"}
_SHORT_LABEL = 40
_LABEL_LIMIT = 120
_DAY_MS = 86_400_000


def _line(value):
    return " ".join((value or "").split())[:_LABEL_LIMIT]


def _plain(value):
    text = _CLOZE.sub(r"\1", _SOUND.sub(" ", _HIDDEN.sub(" ", value or "")))
    return html.unescape(re.sub(r"<[^>]*>", " ", text))


def _text(value):
    return _line(_plain(value))


def _identifier(value):
    return bool(_ID.fullmatch(value) or _HEX.fullmatch(value) and any(letter.isdigit() for letter in value))


def _label_plain(value):
    # Strip before truncation, and again after HTML decoding for escaped placeholders.
    source = _PLACEHOLDER.sub(" ", _CLOZE.sub(r"\1", value or ""))
    return _PLACEHOLDER.sub(" ", _plain(source))


def _clean_label(value):
    return _line(_label_plain(value))


def _label_text(value):
    """Keep real words, never template/type placeholders or ID tokens."""
    text = _label_plain(value)
    return _line(" ".join(word for word in text.split() if not _identifier(word.strip("()[]{}.,;"))))


def _front_values(template, fields):
    """Read field references in order; unsupported/malformed templates use rendered fallback."""
    if not isinstance(template, str):
        return None
    template = _HIDDEN.sub(" ", template)
    tags = list(_TAG.finditer(template))
    remainder = _TAG.sub("", template)
    if not tags or "{{" in remainder or "}}" in remainder:
        return None
    active, found = [], []
    for match in tags:
        tag = match[1].strip()
        if tag.startswith(("#", "^")):
            name = tag[1:].strip()
            if name not in fields:
                return None
            present = bool(_text(fields[name]) or re.search(r"<(?:img|audio|video)\b|\[sound:", fields[name], re.I))
            active.append((name, present if tag[0] == "#" else not present))
        elif tag.startswith("/"):
            if not active or active.pop()[0] != tag[1:].strip():
                return None
        elif all(show for _, show in active):
            parts = [part.strip() for part in tag.split(":")]
            if parts[-1] in _SPECIAL or any(part in ("type", "hint") for part in parts[:-1]):
                continue
            name = tag if tag in fields else parts[-1]
            if name not in fields:
                return None
            found.append(fields[name])
    return None if active else found


def _suggest(question, fields, cloze, template=None, names=()):
    if cloze:
        front = next((field for field in fields if _CLOZE.search(field)), "")
        # A cloze deletion can intentionally be a number, such as a historical year.
        if front:
            return _clean_label(front)
        values = fields
    else:
        shown = _front_values(template, dict(zip(names, fields)))
        if shown is not None:
            labels = list(dict.fromkeys(filter(None, map(_label_text, shown))))
            if labels:
                return " · ".join(labels[:2]) if len(labels) > 1 and all(len(x) <= _SHORT_LABEL for x in labels[:2]) else labels[0]
            values = fields
        else:
            values = [question, *fields]
    return next((text for value in values if (text := _label_text(value))), "")


def _local(col, at):
    """Read on the collection thread. No card text or deck name is sent to the server."""
    try:
        cid = col.db.scalar("select cid from revlog where id = ?", at)
        if not cid:
            return "", ""
        card = col.get_card(cid)
        note = card.note()
        try:
            question = card.question()
        except Exception:
            question = ""
        notetype = note.note_type()
        try:
            template = card.template().get("qfmt")
        except Exception:
            template = None
        names = [field["name"] for field in notetype.get("flds", [])]
        label = _suggest(question, note.fields, notetype.get("type") == 1, template, names)
        return label, deck_names._name(col.decks.name(card.odid or card.did))
    except Exception as error:
        print("ankiquest local conquest:", error)
        return "", ""


def _path(api, at):
    return "/api/conquests/%s/%d" % (api.user, at)


def _load(api, at):
    return api._request(_path(api, at))


def _save(api, at, label):
    value = _line(label)
    if value:
        return api._request(_path(api, at) + "/label", {"label": value})
    return api._request(_path(api, at) + "/label", method="DELETE")


def _tell(api, at):
    return api._request(_path(api, at) + "/tell", {})


def _undo(api, at):
    return api._request(_path(api, at) + "/tell", method="DELETE")


def _can_undo(found, now):
    return bool(found.get("told") and (found.get("undo_until") or 0) > now)


def _days(card):
    # Android and the website round half-days up, with at least one day to learn.
    return max(1, (card["at"] - card["since"] + _DAY_MS // 2) // _DAY_MS)


def _win(api, at, found, deck, translate):
    # Only the saved server label is public. Suggestions and note fields stay local.
    label, card = found.get("label"), found.get("conquest", {})
    title = translate("I conquered a card!")
    if "lapses" not in card:
        words = label or title
    elif label:
        words = language._plural("I finally learned “%s”, a card I had forgotten %d time.",
                                 "I finally learned “%s”, a card I had forgotten %d times.",
                                 card["lapses"], translate) % (label, card["lapses"])
    else:
        words = language._plural("I finally learned a card I had forgotten %d time.",
                                 "I finally learned a card I had forgotten %d times.",
                                 card["lapses"], translate) % card["lapses"]
    if deck:
        words += "\n" + translate("From my deck “%s”.") % deck

    # The local picture includes the same public counts as Android, without a page link.
    details = [words]
    if "answers" in card:
        details.append(language._plural("%d answer", "%d answers", card["answers"], translate) % card["answers"])
    if "at" in card and "since" in card:
        days = _days(card)
        details.append(language._plural("%d day to learn", "%d days to learn", days, translate) % days)
    page = "%s/conquered/%s/%d" % (api.base, api.user, at)
    return {"title": title, "body": words + "\n" + page, "win": share.win_id(found),
            "picture_body": "\n".join(details),
            "picture_pose": "aki_winner" if card.get("leech") else "aki_deck_conquered"}


def _stats(found, translate):
    card = found["conquest"]
    days = _days(card)
    return " · ".join((
        language._plural("%d lapse", "%d lapses", card["lapses"], translate) % card["lapses"],
        language._plural("%d answer", "%d answers", card["answers"], translate) % card["answers"],
        language._plural("%d day to learn", "%d days to learn", days, translate) % days,
    ))
