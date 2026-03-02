from __future__ import annotations

import re
from litellm import completion

from app.prompt import SYSTEM_PROMPT
from app.guardrails import route_message

PROJECT_ID = "ieor-4576-jinxuan"
LOCATION = "us-central1"
MODEL_NAME = "vertex_ai/gemini-2.0-flash-lite"


# If model starts talking about unsupported features, we override to OOS response
POST_OOS_ADVANCED_PATTERNS = [
    r"(?im)^\s*with\s+\w+\s+as\s*\(",
    r"\bover\s*\(",
    r"\bhaving\b",
    r"\bunion\b|\bintersect\b|\bexcept\b",
    r"\binsert\b|\bupdate\b|\bdelete\b|\bcreate\b|\balter\b|\bdrop\b|\btruncate\b",
]

POST_UNCERTAIN_PATTERNS = [
    r"\bnot\s+sure\b",
    r"\bdepends\b",
    r"\bcan['’]?t\s+tell\b|\bcannot\s+tell\b",
    r"\bneed\s+more\s+info\b",
    r"\bneed\s+the\s+schema\b|\bneed\s+schema\b",
    r"\bneed\s+sample\b|\bneed\s+example\b",
]


def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def post_generation_backstop(output_text: str, user_message: str, mode: str) -> str:
    """
    After-generation backstop.

    - smalltalk: don't enforce Clause Summary
    - in_domain:
        * advanced SQL mentions -> controlled out-of-scope
        * uncertainty language -> escape hatch
        * ensure Clause Summary exists (append if missing)
    """
    t = (output_text or "").strip()

    # smalltalk / concept
    if mode in {"smalltalk", "in_domain_concept"}:
        return t

    # in_domain only
    if _match_any(POST_OOS_ADVANCED_PATTERNS, t):
        return (
            "Out of scope: This involves SQL features outside the supported scope.\n"
            "I can help with: SELECT, FROM, WHERE, JOIN, GROUP BY, COUNT, SUM, AVG, MIN, MAX."
        )

    if _match_any(POST_UNCERTAIN_PATTERNS, t):
        return (
            "Uncertain: I’m missing key context (like table schema or expected output).\n"
            "Question: What tables/columns are involved (or what output do you expect)?"
        )

    # If Clause Summary is missing, append a minimal one derived from the query signals
    if "clause summary:" not in t.lower():
        ql = (user_message or "").lower()
        items: list[str] = []
        if re.search(r"\bselect\b", ql): items.append("SELECT")
        if re.search(r"\bfrom\b", ql): items.append("FROM")
        if re.search(r"\bwhere\b", ql): items.append("WHERE")
        if re.search(r"\bjoin\b", ql): items.append("JOIN")
        if re.search(r"\bgroup\s+by\b", ql): items.append("GROUP BY")
        if re.search(r"\bcount\s*\(", ql): items.append("COUNT")
        if re.search(r"\bsum\s*\(", ql): items.append("SUM")
        if re.search(r"\bavg\s*\(", ql): items.append("AVG")
        if re.search(r"\bmin\s*\(", ql): items.append("MIN")
        if re.search(r"\bmax\s*\(", ql): items.append("MAX")
        if items:
            t = t.rstrip() + "\n\nClause Summary: " + " + ".join(items)

    return t


def build_prompt(user_message: str, mode: str) -> str:
    """
    Build a user prompt depending on mode.
    - smalltalk: friendly invite to paste SQL
    - in_domain_concept: answer concept question (no Clause Summary requirement)
    - in_domain: explain a SQL query and end with Clause Summary line
    """
    if mode == "smalltalk":
        return (
            f"User message: {user_message}\n"
            "Reply briefly and friendly, and invite them to paste a SQL query to explain."
        )

    if mode == "in_domain_concept":
        return f"""Answer this SQL concept question in a friendly live-chat style.
- Keep it short (4–8 sentences).
- If helpful, include ONE tiny example query.
- Do NOT say "Out of scope" for SQL concept questions.
- End with one inviting line like: "If you paste a query, I can explain it too."

Question:
{user_message}
""".strip()

    # default: in_domain SQL query explanation
    ql = (user_message or "").lower()
    must_lines: list[str] = []

    if re.search(r"\bon\b", ql):
        must_lines.append('Include the word "ON" in your explanation (exact token ON).')

    if re.search(r"\binner\s+join\b", ql):
        must_lines.append('Include the phrase "INNER JOIN" in your explanation (exact phrase INNER JOIN).')

    if re.search(r"\bleft\s+join\b", ql):
        must_lines.append('Include the phrase "LEFT JOIN" in your explanation (exact phrase LEFT JOIN).')

    must_block = "\n".join([f"- {x}" for x in must_lines]) if must_lines else "- (none)"

    return f"""Explain this SQL query in a natural chat style.
- Use 3–7 bullet points.
- ONLY explain clauses that appear. Do NOT mention missing clauses.
- Keep it short and clear.

Additional requirements:
{must_block}

End with exactly one line:
Clause Summary: <items joined by " + ">

Query:
{user_message}
""".strip()


def generate_answer(user_message: str, mode: str | None = None) -> str:
    """
    Call Gemini (via Vertex AI) using LiteLLM and return the model output text.

    IMPORTANT:
    - We do routing here too (so eval/run_eval.py works even if it calls generate_answer directly).
    - main.py can still pass a mode; routing will always safety-check first.
    """
    decision = route_message(user_message)
    routed_mode = decision["type"]

    # Always honor safety / OOS / uncertain without calling the model
    if routed_mode in {
        "safety",
        "uncertain",
        "oos_non_sql",
        "oos_missing_query",
        "oos_advanced_sql",
        "out_of_scope",  # for backward-compat if it ever appears
    }:
        return decision["response"]

    # If caller passed a mode, use it; otherwise use routed mode
    final_mode = mode or routed_mode

    prompt = build_prompt(user_message, final_mode)

    resp = completion(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        vertex_project=PROJECT_ID,
        vertex_location=LOCATION,
    )

    raw = resp.choices[0].message.content.strip()
    return post_generation_backstop(raw, user_message=user_message, mode=final_mode)