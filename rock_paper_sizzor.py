"""
Local Markdown Chatbot (Copilot-style) — No APIs, No Internet
Run:
    python local_copilot.py

Features:
- Copilot-like responses: concise, empathetic, structured Markdown (headings, lists, tables).
- Math mode with LaTeX steps: "math: 2+3*4" or "math: solve 2x+3=11".
- Compare/rank mode auto-creates tables: "compare: phones | price, battery, camera".
- Explain/summarize mode: "explain: topic", "summarize: text here".
- Brainstorm mode: "brainstorm: project idea about ...".
- Safety guardrails: refuses harmful requests, medical/therapy advice.
- Tiny offline knowledge shard (limited facts) for demos.

Notes:
- This is intentionally small and offline. It won't browse or cite sources.
- Markdown tables/LaTeX render best in viewers that support them.
"""

import ast
import operator
import re
import sys
from typing import List, Dict, Tuple, Optional

# -----------------------------
# Persona and style settings
# -----------------------------
STYLE = {
    "max_sections": 6,
    "max_table_cols": 5,
    "short_reply_threshold": 140,  # characters
}

# -----------------------------
# Safety guardrails
# -----------------------------
HARMFUL_PATTERNS = [
    r"suicide", r"kill myself", r"harm myself", r"self[-\s]?harm",
    r"harm others", r"hurt someone", r"violence", r"bomb", r"weapon",
    r"abuse", r"poison", r"overdose",
]
MEDICAL_PATTERNS = [
    r"diagnose", r"symptom", r"treatment", r"medication", r"dose", r"therapy",
    r"side effect", r"prescribe", r"prognosis",
]

def is_harmful(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in HARMFUL_PATTERNS)

def is_medical(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in MEDICAL_PATTERNS)

# -----------------------------
# Tiny offline knowledge shard (demo only)
# -----------------------------
FACTS: Dict[str, str] = {
    "best metal conductor of heat": "Silver has the highest thermal conductivity among common metals; copper is close.",
    "diamond thermal conductivity": "Diamond (not a metal) has extremely high thermal conductivity.",
    "ohm law": "Ohm’s law: V = I × R.",
    "newton second law": "Newton’s second law: F = m × a.",
    "python list": "A Python list is an ordered, mutable collection supporting indexing and slicing.",
}

def lookup_fact(q: str) -> Optional[str]:
    q = q.lower().strip()
    for k, v in FACTS.items():
        if k in q:
            return v
    return None

# -----------------------------
# Markdown helpers
# -----------------------------
def h(level: int, text: str) -> str:
    level = max(1, min(6, level))
    return f"{'#' * level} {text}"

def bullet(label: str, desc: str) -> str:
    return f"- **{label}:** {desc}"

def table(headers: List[str], rows: List[List[str]]) -> str:
    if not headers:
        return ""
    headers = headers[:STYLE["max_table_cols"]]
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        row = row[:len(headers)]
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)

# -----------------------------
# Math engine (safe eval + simple solve)
# -----------------------------
ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
}
def safe_eval_expr(node):
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](safe_eval_expr(node.left), safe_eval_expr(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](safe_eval_expr(node.operand))
    raise ValueError("Unsupported expression")

def math_calculate(expr: str) -> Tuple[str, Optional[float]]:
    try:
        node = ast.parse(expr, mode='eval').body
        val = safe_eval_expr(node)
        steps = f"- **Expression:** \({expr}\)\n- **Result:** \({val}\)"
        return steps, float(val)
    except Exception:
        return "- **Note:** I can only handle basic arithmetic (e.g., 2+3*4, (1+2)**3).", None

def solve_linear(eq: str) -> str:
    """
    Solve ax + b = c for x. Supports forms like '2x+3=11', 'x-5=10', '3x=12'.
    """
    eq = eq.replace(" ", "")
    if "=" not in eq:
        return "- **Note:** Please provide an equation like 2x+3=11."
    left, right = eq.split("=", 1)
    # Extract coefficients from left: ax + b
    # Handle cases: '2x+3', 'x-5', '3x'
    m = re.match(r"^([+-]?\d*)x([+-]\d+)?$", left)
    if not m:
        return "- **Note:** I can only solve simple linear equations like 2x+3=11."
    a_str, b_str = m.groups()
    a = 1 if a_str in ("", "+") else (-1 if a_str == "-" else int(a_str))
    b = int(b_str) if b_str else 0
    try:
        c = int(right)
    except ValueError:
        return "- **Note:** Right-hand side should be a number."
    # Solve: ax + b = c => x = (c - b) / a
    try:
        x = (c - b) / a
    except ZeroDivisionError:
        return "- **Note:** Coefficient of x cannot be zero for a linear equation."
    return "\n".join([
        "- **Given:** \(" + eq.replace("^", "**") + "\)",
        "- **Rearrange:** \(ax + b = c \Rightarrow x = \frac{c - b}{a}\)",
        f"- **Compute:** \(\frac{{{c} - {b}}}{{{a}}} = {x}\)",
        f"- **Solution:** \(x = {x}\)",
    ])

# -----------------------------
# Intent detection
# -----------------------------
def detect_intent(text: str) -> str:
    t = text.strip().lower()
    if t.startswith("math:"):
        return "math"
    if t.startswith("compare:"):
        return "compare"
    if t.startswith("rank:"):
        return "rank"
    if t.startswith("explain:"):
        return "explain"
    if t.startswith("summarize:"):
        return "summarize"
    if t.startswith("brainstorm:"):
        return "brainstorm"
    return "chat"

# -----------------------------
# Compare/Rank helpers
# -----------------------------
def parse_compare_payload(t: str) -> Tuple[List[str], List[str]]:
    """
    Format: "compare: items a,b,c | attrs price,battery"
    """
    payload = t.split("compare:", 1)[-1].strip()
    parts = [p.strip() for p in payload.split("|")]
    items = parts[0] if parts else ""
    attrs = parts[1] if len(parts) > 1 else ""
    item_list = [x.strip() for x in items.split(",") if x.strip()]
    attr_list = [x.strip() for x in attrs.split(",") if x.strip()]
    return item_list, attr_list

def rank_items(items: List[str]) -> List[str]:
    # Placeholder ranking: alphabetical
    return sorted(items, key=lambda s: s.lower())

# -----------------------------
# Response builders
# -----------------------------
def respond_chat(user: str) -> str:
    if is_harmful(user):
        return "\n".join([
            h(3, "I can’t help with that"),
            "I’m here to keep you safe and informed. I can’t assist with harming yourself or others.",
            "If you want general information or a different topic, I’m here for that.",
        ])
    if is_medical(user):
        return "\n".join([
            h(3, "General guidance only"),
            "I can share general information, but I can’t provide medical advice or diagnoses.",
            "Consider speaking to a qualified professional for personalized support.",
        ])
    # Simple facts fallback
    fact = lookup_fact(user)
    if fact:
        return "\n".join([
            h(3, "Direct answer"),
            fact,
        ])
    # Default conversational style
    simple = len(user) < STYLE["short_reply_threshold"]
    if simple:
        return "Got it. Want a quick breakdown or a deeper dive?"
    return "\n".join([
        h(2, "Overview"),
        "Here’s a concise, structured take tailored to your prompt.",
        "",
        h(3, "Key points"),
        "\n".join([
            bullet("Context", "I’m offline, so I’ll focus on reasoning and clarity."),
            bullet("Assumptions", "I infer intent from your wording and keep answers concise."),
            bullet("Next step", "Ask for a comparison, math, or a summary for more structure."),
        ]),
    ])

def respond_math(user: str) -> str:
    payload = user.split("math:", 1)[-1].strip()
    if payload.startswith("solve"):
        eq = payload.split("solve", 1)[-1].strip()
        return "\n".join([h(2, "Linear equation solution"), solve_linear(eq)])
    steps, val = math_calculate(payload)
    return "\n".join([h(2, "Computation"), steps])

def respond_explain(user: str) -> str:
    topic = user.split("explain:", 1)[-1].strip() or "that topic"
    return "\n".join([
        h(2, f"Explainer: {topic}"),
        h(3, "Core idea"),
        "Think of it as a system with inputs, a transformation, and outputs—optimize the transformation.",
        h(3, "Why it matters"),
        "\n".join([
            bullet("Clarity", "It reduces ambiguity and helps decisions."),
            bullet("Speed", "Clear models shorten feedback loops."),
            bullet("Reliability", "Explicit assumptions avoid hidden errors."),
        ]),
    ])

def respond_summarize(user: str) -> str:
    text = user.split("summarize:", 1)[-1].strip()
    if not text:
        return "\n".join([h(3, "I need the text"), "Paste the content after 'summarize:'"])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    bullets = [bullet(f"Point {i+1}", s) for i, s in enumerate(sentences[:6])]
    return "\n".join([h(2, "Summary"), "\n".join(bullets)])

def respond_brainstorm(user: str) -> str:
    topic = user.split("brainstorm:", 1)[-1].strip() or "your idea"
    ideas = [
        ("Lean pilot", "Ship a minimal core to validate demand quickly."),
        ("Delight hooks", "Add one playful feature users talk about."),
        ("Data loop", "Instrument usage to learn and iterate weekly."),
        ("Partner angle", "Find a collaborator who amplifies reach."),
    ]
    rows = [[name, desc] for name, desc in ideas]
    t = table(["Idea", "Why"], rows)
    return "\n".join([h(2, f"Brainstorm: {topic}"), t])

def respond_compare(user: str) -> str:
    items, attrs = parse_compare_payload(user)
    if not items or not attrs:
        return "\n".join([
            h(3, "I need items and attributes"),
            "Format: compare: item1, item2 | price, battery, camera",
        ])
    rows = [[it] + ["—"] * len(attrs) for it in items]
    t = table(["Item"] + attrs, rows)
    return "\n".join([h(2, "Comparison"), t])

def respond_rank(user: str) -> str:
    items = [x.strip() for x in user.split("rank:", 1)[-1].split(",") if x.strip()]
    if not items:
        return "\n".join([h(3, "I need items"), "Format: rank: item1, item2, item3"])
    ranked = rank_items(items)
    rows = [[str(i+1), it] for i, it in enumerate(ranked)]
    t = table(["Rank", "Item"], rows)
    return "\n".join([h(2, "Ranking"), t])

# -----------------------------
# Main loop
# -----------------------------
HELP_TEXT = "\n".join([
    h(2, "Commands"),
    "\n".join([
        bullet("Chat", "Just type your message."),
        bullet("Math", "math: 2+3*4 or math: solve 2x+3=11"),
        bullet("Explain", "explain: topic"),
        bullet("Summarize", "summarize: paste text"),
        bullet("Brainstorm", "brainstorm: your idea"),
        bullet("Compare", "compare: a,b,c | price,battery"),
        bullet("Rank", "rank: a, b, c"),
        bullet("Quit", "/exit or Ctrl+C"),
    ]),
])

def respond(user: str) -> str:
    intent = detect_intent(user)
    if intent == "math":
        return respond_math(user)
    if intent == "compare":
        return respond_compare(user)
    if intent == "rank":
        return respond_rank(user)
    if intent == "explain":
        return respond_explain(user)
    if intent == "summarize":
        return respond_summarize(user)
    if intent == "brainstorm":
        return respond_brainstorm(user)
    return respond_chat(user)

def main():
    print(h(1, "Local Copilot-style chatbot"))
    print("Type /help for commands. No internet, no APIs.")
    while True:
        try:
            user = input("> ").strip()
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        if not user:
            continue
        if user.lower() in ("/exit", "exit", "quit"):
            print("Goodbye.")
            break
        if user.lower() == "/help":
            print(HELP_TEXT)
            continue
        print(respond(user))


import ast
import operator
import re
import sys
from typing import List, Dict, Tuple, Optional

# -----------------------------
# Persona and style settings
# -----------------------------
STYLE = {
    "max_sections": 6,
    "max_table_cols": 5,
    "short_reply_threshold": 140,  # characters
}

# -----------------------------
# Safety guardrails
# -----------------------------
HARMFUL_PATTERNS = [
    r"suicide", r"kill myself", r"harm myself", r"self[-\s]?harm",
    r"harm others", r"hurt someone", r"violence", r"bomb", r"weapon",
    r"abuse", r"poison", r"overdose",
]
MEDICAL_PATTERNS = [
    r"diagnose", r"symptom", r"treatment", r"medication", r"dose", r"therapy",
    r"side effect", r"prescribe", r"prognosis",
]

def is_harmful(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in HARMFUL_PATTERNS)

def is_medical(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in MEDICAL_PATTERNS)

# -----------------------------
# Tiny offline knowledge shard (demo only)
# -----------------------------
FACTS: Dict[str, str] = {
    "best metal conductor of heat": "Silver has the highest thermal conductivity among common metals; copper is close.",
    "diamond thermal conductivity": "Diamond (not a metal) has extremely high thermal conductivity.",
    "ohm law": "Ohm’s law: V = I × R.",
    "newton second law": "Newton’s second law: F = m × a.",
    "python list": "A Python list is an ordered, mutable collection supporting indexing and slicing.",
}

def lookup_fact(q: str) -> Optional[str]:
    q = q.lower().strip()
    for k, v in FACTS.items():
        if k in q:
            return v
    return None

# -----------------------------
# Markdown helpers
# -----------------------------
def h(level: int, text: str) -> str:
    level = max(1, min(6, level))
    return f"{'#' * level} {text}"

def bullet(label: str, desc: str) -> str:
    return f"- **{label}:** {desc}"

def table(headers: List[str], rows: List[List[str]]) -> str:
    if not headers:
        return ""
    headers = headers[:STYLE["max_table_cols"]]
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        row = row[:len(headers)]
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)

# -----------------------------
# Math engine (safe eval + simple solve)
# -----------------------------
ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
}
def safe_eval_expr(node):
    if isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](safe_eval_expr(node.left), safe_eval_expr(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](safe_eval_expr(node.operand))
    raise ValueError("Unsupported expression")

def math_calculate(expr: str) -> Tuple[str, Optional[float]]:
    try:
        node = ast.parse(expr, mode='eval').body
        val = safe_eval_expr(node)
        steps = f"- **Expression:** \({expr}\)\n- **Result:** \({val}\)"
        return steps, float(val)
    except Exception:
        return "- **Note:** I can only handle basic arithmetic (e.g., 2+3*4, (1+2)**3).", None

def solve_linear(eq: str) -> str:
    """
    Solve ax + b = c for x. Supports forms like '2x+3=11', 'x-5=10', '3x=12'.
    """
    eq = eq.replace(" ", "")
    if "=" not in eq:
        return "- **Note:** Please provide an equation like 2x+3=11."
    left, right = eq.split("=", 1)
    # Extract coefficients from left: ax + b
    # Handle cases: '2x+3', 'x-5', '3x'
    m = re.match(r"^([+-]?\d*)x([+-]\d+)?$", left)
    if not m:
        return "- **Note:** I can only solve simple linear equations like 2x+3=11."
    a_str, b_str = m.groups()
    a = 1 if a_str in ("", "+") else (-1 if a_str == "-" else int(a_str))
    b = int(b_str) if b_str else 0
    try:
        c = int(right)
    except ValueError:
        return "- **Note:** Right-hand side should be a number."
    # Solve: ax + b = c => x = (c - b) / a
    try:
        x = (c - b) / a
    except ZeroDivisionError:
        return "- **Note:** Coefficient of x cannot be zero for a linear equation."
    return "\n".join([
        "- **Given:** \(" + eq.replace("^", "**") + "\)",
        "- **Rearrange:** \(ax + b = c \Rightarrow x = \frac{c - b}{a}\)",
        f"- **Compute:** \(\frac{{{c} - {b}}}{{{a}}} = {x}\)",
        f"- **Solution:** \(x = {x}\)",
    ])

# -----------------------------
# Intent detection
# -----------------------------
def detect_intent(text: str) -> str:
    t = text.strip().lower()
    if t.startswith("math:"):
        return "math"
    if t.startswith("compare:"):
        return "compare"
    if t.startswith("rank:"):
        return "rank"
    if t.startswith("explain:"):
        return "explain"
    if t.startswith("summarize:"):
        return "summarize"
    if t.startswith("brainstorm:"):
        return "brainstorm"
    return "chat"

# -----------------------------
# Compare/Rank helpers
# -----------------------------
def parse_compare_payload(t: str) -> Tuple[List[str], List[str]]:
    """
    Format: "compare: items a,b,c | attrs price,battery"
    """
    payload = t.split("compare:", 1)[-1].strip()
    parts = [p.strip() for p in payload.split("|")]
    items = parts[0] if parts else ""
    attrs = parts[1] if len(parts) > 1 else ""
    item_list = [x.strip() for x in items.split(",") if x.strip()]
    attr_list = [x.strip() for x in attrs.split(",") if x.strip()]
    return item_list, attr_list

def rank_items(items: List[str]) -> List[str]:
    # Placeholder ranking: alphabetical
    return sorted(items, key=lambda s: s.lower())

# -----------------------------
# Response builders
# -----------------------------
def respond_chat(user: str) -> str:
    if is_harmful(user):
        return "\n".join([
            h(3, "I can’t help with that"),
            "I’m here to keep you safe and informed. I can’t assist with harming yourself or others.",
            "If you want general information or a different topic, I’m here for that.",
        ])
    if is_medical(user):
        return "\n".join([
            h(3, "General guidance only"),
            "I can share general information, but I can’t provide medical advice or diagnoses.",
            "Consider speaking to a qualified professional for personalized support.",
        ])
    # Simple facts fallback
    fact = lookup_fact(user)
    if fact:
        return "\n".join([
            h(3, "Direct answer"),
            fact,
        ])
    # Default conversational style
    simple = len(user) < STYLE["short_reply_threshold"]
    if simple:
        return "Got it. Want a quick breakdown or a deeper dive?"
    return "\n".join([
        h(2, "Overview"),
        "Here’s a concise, structured take tailored to your prompt.",
        "",
        h(3, "Key points"),
        "\n".join([
            bullet("Context", "I’m offline, so I’ll focus on reasoning and clarity."),
            bullet("Assumptions", "I infer intent from your wording and keep answers concise."),
            bullet("Next step", "Ask for a comparison, math, or a summary for more structure."),
        ]),
    ])

def respond_math(user: str) -> str:
    payload = user.split("math:", 1)[-1].strip()
    if payload.startswith("solve"):
        eq = payload.split("solve", 1)[-1].strip()
        return "\n".join([h(2, "Linear equation solution"), solve_linear(eq)])
    steps, val = math_calculate(payload)
    return "\n".join([h(2, "Computation"), steps])

def respond_explain(user: str) -> str:
    topic = user.split("explain:", 1)[-1].strip() or "that topic"
    return "\n".join([
        h(2, f"Explainer: {topic}"),
        h(3, "Core idea"),
        "Think of it as a system with inputs, a transformation, and outputs—optimize the transformation.",
        h(3, "Why it matters"),
        "\n".join([
            bullet("Clarity", "It reduces ambiguity and helps decisions."),
            bullet("Speed", "Clear models shorten feedback loops."),
            bullet("Reliability", "Explicit assumptions avoid hidden errors."),
        ]),
    ])

def respond_summarize(user: str) -> str:
    text = user.split("summarize:", 1)[-1].strip()
    if not text:
        return "\n".join([h(3, "I need the text"), "Paste the content after 'summarize:'"])
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    bullets = [bullet(f"Point {i+1}", s) for i, s in enumerate(sentences[:6])]
    return "\n".join([h(2, "Summary"), "\n".join(bullets)])

def respond_brainstorm(user: str) -> str:
    topic = user.split("brainstorm:", 1)[-1].strip() or "your idea"
    ideas = [
        ("Lean pilot", "Ship a minimal core to validate demand quickly."),
        ("Delight hooks", "Add one playful feature users talk about."),
        ("Data loop", "Instrument usage to learn and iterate weekly."),
        ("Partner angle", "Find a collaborator who amplifies reach."),
    ]
    rows = [[name, desc] for name, desc in ideas]
    t = table(["Idea", "Why"], rows)
    return "\n".join([h(2, f"Brainstorm: {topic}"), t])

def respond_compare(user: str) -> str:
    items, attrs = parse_compare_payload(user)
    if not items or not attrs:
        return "\n".join([
            h(3, "I need items and attributes"),
            "Format: compare: item1, item2 | price, battery, camera",
        ])
    rows = [[it] + ["—"] * len(attrs) for it in items]
    t = table(["Item"] + attrs, rows)
    return "\n".join([h(2, "Comparison"), t])

def respond_rank(user: str) -> str:
    items = [x.strip() for x in user.split("rank:", 1)[-1].split(",") if x.strip()]
    if not items:
        return "\n".join([h(3, "I need items"), "Format: rank: item1, item2, item3"])
    ranked = rank_items(items)
    rows = [[str(i+1), it] for i, it in enumerate(ranked)]
    t = table(["Rank", "Item"], rows)
    return "\n".join([h(2, "Ranking"), t])

# -----------------------------
# Main loop
# -----------------------------
HELP_TEXT = "\n".join([
    h(2, "Commands"),
    "\n".join([
        bullet("Chat", "Just type your message."),
        bullet("Math", "math: 2+3*4 or math: solve 2x+3=11"),
        bullet("Explain", "explain: topic"),
        bullet("Summarize", "summarize: paste text"),
        bullet("Brainstorm", "brainstorm: your idea"),
        bullet("Compare", "compare: a,b,c | price,battery"),
        bullet("Rank", "rank: a, b, c"),
        bullet("Quit", "/exit or Ctrl+C"),
    ]),
])

def respond(user: str) -> str:
    intent = detect_intent(user)
    if intent == "math":
        return respond_math(user)
    if intent == "compare":
        return respond_compare(user)
    if intent == "rank":
        return respond_rank(user)
    if intent == "explain":
        return respond_explain(user)
    if intent == "summarize":
        return respond_summarize(user)
    if intent == "brainstorm":
        return respond_brainstorm(user)
    return respond_chat(user)

def main():
    print(h(1, "Local Copilot-style chatbot"))
    print("Type /help for commands. No internet, no APIs.")
    while True:
        try:
            user = input("> ").strip()
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        if not user:
            continue
        if user.lower() in ("/exit", "exit", "quit"):
            print("Goodbye.")
            break
        if user.lower() == "/help":
            print(HELP_TEXT)
            continue
        print(respond(user))

if __name__ == "__main__":
    main()