import re

# -----------------------------
# Helpers
# -----------------------------

def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)

def _normalize(text: str) -> str:
    return (text or "").strip()


# -----------------------------
# Safety (highest priority)
# -----------------------------
# Goal: Catch self-harm even when mixed with SQL.
SAFETY_PATTERNS = [
    # direct
    r"\bkill\s+myself\b",
    r"\bsuicide\b",
    r"\bself[-\s]?harm\b",
    r"\bhurt\s+myself\b",
    r"\bself[-\s]?injur(e|y)\b",

    # paraphrases / euphemisms
    r"\bend\s+my\s+life\b",
    r"\bi\s+want\s+to\s+die\b",
    r"\bwant\s+to\s+die\b",
    r"\bunalive\b",
    r"\bkms\b",

    # method references (still safety route)
    r"\boverdose\b",
    r"\bhang\s+myself\b",
    r"\bjump\s+off\b",
    r"\bcut\s+myself\b",

    # instructions phrasing
    r"\binstructions?\b[\s\S]{0,80}\b(hurt|kill|self[-\s]?harm|suicide)\b",
    r"\bhow\s+to\b[\s\S]{0,80}\b(hurt|kill|self[-\s]?harm|suicide)\b",
]


def is_safety_trigger(text: str) -> bool:
    return _match_any(SAFETY_PATTERNS, text)


# -----------------------------
# Smalltalk / basic greeting
# -----------------------------
SMALLTALK_PATTERNS = [
    r"^\s*(hi|hello|hey)\b",
    r"\bgood\s+(morning|afternoon|evening)\b",
    r"^\s*thanks\b|\bthank you\b",
]


def is_smalltalk(text: str) -> bool:
    t = _normalize(text).lower()

    if _match_any(SMALLTALK_PATTERNS, t):
        return True

    # Keep "what is sql" out of smalltalk (it's a concept question)
    if re.search(r"\bwhat\s+is\s+sql\b", t):
        return False

    # Very short messages are usually smalltalk, but don't over-trigger
    words = t.split()
    return len(words) <= 2


# -----------------------------
# SQL detection (make it permissive)
# -----------------------------
# We want to accept most valid SELECT queries, even if missing FROM (e.g., SELECT 1;)
# Also accept supported clauses even if query is wrapped like "Explain: ..."
SQL_SIGNAL_PATTERNS = [
    r"\bselect\b",
    r"\bfrom\b",
    r"\bwhere\b",
    r"\bjoin\b",
    r"\bgroup\s+by\b",
    r"\bcount\s*\(",
    r"\bsum\s*\(",
    r"\bavg\s*\(",
    r"\bmin\s*\(",
    r"\bmax\s*\(",
]


def looks_like_sql(text: str) -> bool:
    t = _normalize(text)
    return _match_any(SQL_SIGNAL_PATTERNS, t)


# -----------------------------
# Out-of-scope SQL (keep strict to "truly advanced" only)
# -----------------------------
ADVANCED_SQL_PATTERNS = [
    r"\bwith\s+\w+\s+as\s*\(",          # CTE
    r"\bover\s*\(",                     # window functions
    r"\bhaving\b",
    r"\bunion\b|\bintersect\b|\bexcept\b",
    r"\bfull\s+(outer\s+)?join\b",
    r"\bright\s+join\b",
    r"\binsert\b|\bupdate\b|\bdelete\b|\bmerge\b",
    r"\bcreate\b|\balter\b|\bdrop\b|\btruncate\b",
]

def looks_like_advanced_sql(text: str) -> bool:
    t = _normalize(text)
    return _match_any(ADVANCED_SQL_PATTERNS, t)


# -----------------------------
# Escape hatch
# -----------------------------
ASK_TO_EXPLAIN_PATTERNS = [
    r"\bexplain\b",
    r"\bbreak\s+down\b",
    r"\bwalk\s+me\s+through\b",
]

MISSING_CONTEXT_PATTERNS = [
    r"\boptimi[sz]e\b",
    r"\bmake\s+it\s+faster\b",
    r"\bwhy\s+is\s+this\s+slow\b",
    r"\bindex\b|\bindexes\b",
    r"\bquery\s+plan\b|\bexplain\s+plan\b",
    r"\bperformance\b",
]

def asked_to_explain_but_no_query(text: str) -> bool:
    """
    If user says "explain" but there's no SQL signal at all.
    """
    t = _normalize(text)
    if _match_any(ASK_TO_EXPLAIN_PATTERNS, t) and not looks_like_sql(t):
        return True
    return False

def needs_missing_context_escape_hatch(text: str) -> bool:
    """
    If user asks perf/optimization but doesn't include a query.
    """
    t = _normalize(text)
    if _match_any(MISSING_CONTEXT_PATTERNS, t) and not looks_like_sql(t):
        return True
    return False


# -----------------------------
# Routing
# -----------------------------
def route_message(text: str) -> dict:
    """
    Route message into one of:
    - safety
    - in_domain
    - smalltalk
    - uncertain (escape hatch)
    - oos_advanced_sql
    - oos_missing_query
    - oos_non_sql
    """
    t = _normalize(text)

    # 1) Safety first (even if mixed with SQL)
    if is_safety_trigger(t):
        return {
            "type": "safety",
            "response": "If you are in immediate danger, please contact local emergency services."
        }

    # 2) Missing query escape hatch ("explain this" but no SQL)
    if asked_to_explain_but_no_query(t):
        return {
            "type": "oos_missing_query",
            "response": (
                "Out of scope: I don’t see a SQL query to explain.\n"
                "I can help with: SELECT, FROM, WHERE, JOIN, GROUP BY, COUNT, SUM, AVG, MIN, MAX."
            )
        }

    # 3) Optimization/perf request without query -> escape hatch
    if needs_missing_context_escape_hatch(t):
        return {
            "type": "oos_missing_query",
            "response": (
                "Out of scope: I don’t see a SQL query to explain.\n"
                "I can help with: SELECT, FROM, WHERE, JOIN, GROUP BY, COUNT, SUM, AVG, MIN, MAX."
            )
        }
    # 4) SQL present but truly advanced features -> OOS advanced category
    if looks_like_sql(t) and looks_like_advanced_sql(t):
        return {
            "type": "oos_advanced_sql",
            "response": (
                "Out of scope: This query uses advanced SQL features outside the supported scope.\n"
                "I can help with: SELECT, FROM, WHERE, JOIN, GROUP BY, COUNT, SUM, AVG, MIN, MAX."
            )
        }

    # 5) Concept questions (still in-domain, even without concrete SQL query)
    # Put this BEFORE looks_like_sql(), otherwise "what is sql" will fall to oos_non_sql.
    CONCEPT_PATTERNS = [
        r"\bwhat\s+is\s+sql\b",
        r"\bwhat\s+is\s+(a\s+)?database\b",
        r"\bwhat\s+does\s+select\s+do\b",
        r"\bwhat\s+does\s+from\s+do\b",
        r"\bwhat\s+does\s+where\s+do\b",
        r"\bwhat\s+is\s+(an?\s+)?join\b",
        r"\bwhat\s+is\s+(a\s+)?left\s+join\b",
        r"\bwhat\s+is\s+(a\s+)?inner\s+join\b",
        r"\bwhat\s+is\s+(a\s+)?group\s+by\b",
        r"\bwhat\s+is\s+count\b|\bwhat\s+does\s+count\s+do\b",
        r"\bwhat\s+is\s+sum\b|\bwhat\s+does\s+sum\s+do\b",
        r"\bwhat\s+is\s+avg\b|\bwhat\s+does\s+avg\s+do\b",
        r"\bwhat\s+is\s+min\b|\bwhat\s+does\s+min\s+do\b",
        r"\bwhat\s+is\s+max\b|\bwhat\s+does\s+max\s+do\b",
    ]
    if _match_any(CONCEPT_PATTERNS, t.lower()):
        return {"type": "in_domain_concept"}

    # 6) In-domain SQL (permissive): any SQL signal counts
    if looks_like_sql(t):
        return {"type": "in_domain"}

    # 7) Smalltalk
    if is_smalltalk(t):
        return {"type": "smalltalk"}

    # 8) Everything else -> OOS non-sql
    return {
        "type": "oos_non_sql",
        "response": (
            "Out of scope: I can only help with explaining basic SQL query mechanics.\n"
            "I can help with: SELECT, FROM, WHERE, JOIN, GROUP BY, COUNT, SUM, AVG, MIN, MAX."
        )
    }



# -----------------------------
# Deterministic metric (eval)
# -----------------------------
def deterministic_metric(prediction: str, expected_clauses: list) -> bool:
    """
    Deterministic check:
    - For each expected clause, require it to appear somewhere in the response (case-insensitive).
    """
    text = (prediction or "").lower()

    clause_patterns = {
        "select": r"\bselect\b",
        "from": r"\bfrom\b",
        "where": r"\bwhere\b",
        "join": r"\bjoin\b",
        "left join": r"\bleft\s+join\b",
        "inner join": r"\binner\s+join\b",
        "group by": r"\bgroup\s+by\b",
        "count": r"\bcount\b",
        "sum": r"\bsum\b",
        "avg": r"\bavg\b",
        "min": r"\bmin\b",
        "max": r"\bmax\b",
        "on": r"\bon\b",
    }

    for c in expected_clauses:
        key = c.strip().lower()
        pat = clause_patterns.get(key, re.escape(key))
        if not re.search(pat, text):
            return False

    return True