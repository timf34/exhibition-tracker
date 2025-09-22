import re, hashlib
from typing import Optional


def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def normalize_title_key(title: Optional[str]) -> str:
    if not title: return ""
    t = strip_accents(title).casefold()
    t = re.sub(r"[^\w\s-]", "", t)
    return norm_space(t)

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()