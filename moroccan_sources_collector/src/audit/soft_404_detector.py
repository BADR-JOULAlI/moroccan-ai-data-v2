from __future__ import annotations

import re

ZERO_RESULT_PATTERNS = [
    r"\b0 results?\b",
    r"no results",
    r"no repositories found",
    r"your search did not match any repositories",
    r"we couldn.?t find any results",
    r"nothing matched your search",
    r"0 résultat",
    r"aucun résultat",
    r"aucun contenu trouvé",
    r"aucun document trouvé",
    r"لا توجد نتائج",
    r"لم يتم العثور على نتائج",
]
SOFT_404_PATTERNS = [
    r"page not found",
    r"this page does not exist",
    r"page introuvable",
    r"cette page n.?existe pas",
    r"الصفحة غير موجودة",
    r"لا يوجد محتوى",
]
LOGIN_PATTERNS = [
    r"sign in to continue",
    r"log in to continue",
    r"connectez-vous pour continuer",
    r"سجل الدخول للمتابعة",
]
BLOCKED_PATTERNS = [r"captcha", r"cloudflare", r"access denied", r"forbidden", r"too many requests"]


def _find(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.I):
            return pattern
    return ""


def detect_content_problem(title: str = "", text: str = "", html: str = "") -> dict:
    haystack = " ".join([title or "", text or "", html[:20000] or ""]).lower()
    zero = _find(ZERO_RESULT_PATTERNS, haystack)
    if zero:
        return {"problem": "ZERO_RESULTAT", "message": zero}
    login = _find(LOGIN_PATTERNS, haystack)
    if login:
        return {"problem": "PAGE_CONNEXION", "message": login}
    soft = _find(SOFT_404_PATTERNS, haystack)
    if soft:
        return {"problem": "SOFT_404", "message": soft}
    blocked = _find(BLOCKED_PATTERNS, haystack)
    if blocked:
        return {"problem": "BLOQUEE", "message": blocked}
    return {"problem": "", "message": ""}
