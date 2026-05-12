#!/usr/bin/env python3
"""MCP server: LLM prompt injection & jailbreak scanner.

Detects prompt injection attempts, jailbreak patterns, PII leaks, and
data exfiltration risks in user prompts. Stdlib-only, no external deps.
Use BEFORE sending user input to any LLM, or when auditing prompt logs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("llm-guard")

# ---------------------------------------------------------------------------
# Injection patterns
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # (name, regex, description)
    ("ignore_previous", r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?|directives?)",
     "Attempts to override system instructions"),
    ("role_override", r"(?i)(you\s+are\s+now|from\s+now\s+on\s+you|act\s+as\s+(if\s+)?(a|an)?\s*(evil|unrestricted|unfiltered|malicious|rogue))",
     "Attempts to change the assistant's role"),
    ("system_prompt_leak", r"(?i)(reveal|show|print|output|display|tell\s+me|what\s+(is|are))\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?|guidelines?|directive)",
     "Attempts to extract system prompt"),
    ("delimiter_bypass", r"(?i)(```|'''.*'''|system\s*:|<<SYS>>|\[INST\]|\[SYSTEM\]|système\s*:)",
     "Uses markup to inject system-level instructions"),
    ("token_smuggling", r"(?i)(base64|rot13|hex\s*encode|unicode\s*escape|url\s*encode).*\s*(decode|translate|interpret|convert)",
     "Attempts to hide malicious content via encoding"),
    ("recursive_injection", r"(?i)(now\s+repeat|echo\s+back|say\s+exactly|repeat\s+after\s+me|translate\s+this\s+and\s+execute)",
     "Social engineering to make the LLM repeat instructions"),
    ("payload_in_data", r"(?i)(\{\{.*\}\}|\{\%.*\%\}|\$\{.*\}|<\%.*\%>)",
     "Template/shell injection attempts"),
    ("multi_lang_bypass", r"(?i)(ignore\s+les?\s+instructions?\s+(précédentes?|ci-dessus|antérieures?)|ignor[ií]\s+las?\s+instrucciones?|ignora\s+le?\s+istruzioni?)",
     "Non-English instruction override attempts"),
    ("exfiltration", r"(?i)(send|upload|post|curl|wget|fetch).*(to|at)\s+(https?://|ftp://|[a-z]+\.[a-z]{2,}/)",
     "Attempts to exfiltrate data to external URLs"),
    ("privilege_escalation", r"(?i)(sudo|admin|root|superuser|elevate|bypass\s+permission|disable\s+safety)",
     "Attempts to escalate privileges or disable safety"),
    ("output_constraint", r"(?i)(do\s+not\s+(say|mention|warn|refuse|decline)|never\s+(say|warn|refuse)|under\s+no\s+circumstances)",
     "Attempts to suppress refusal behavior"),
    ("context_pollution", r"(?i)(as\s+a\s+reminder|remember\s+that|important\s+note:\s+you\s+must|critical\s+update:\s+your)",
     "Social engineering through fake context"),
]

JAILBREAK_PATTERNS: list[tuple[str, str, str]] = [
    ("dan_prompt", r"(?i)(DAN|do\s+anything\s+now|jailbreak|developer\s+mode)",
     "Classic DAN / jailbreak trigger"),
    ("aim_prompt", r"(?i)(AIM|always\s+intelligent\s+and\s+machiavellian|unethical|amoral)",
     "Always Intelligent and Machiavellian jailbreak"),
    ("character_break", r"(?i)(you\s+are\s+(no\s+longer|not)\s+an?\s+(AI|assistant|language\s+model))",
     "Character/identity override jailbreak"),
    ("hypothetical_frame", r"(?i)(hypothetically|in\s+a\s+fictional\s+world|imagine\s+you\s+are\s+not|pretend\s+you\s+have\s+no\s+restrictions)",
     "Hypothetical framing to bypass restrictions"),
    ("translation_jb", r"(?i)(translate\s+this\s+(to|into|in)\s+\w+.*(ignore|bypass|hack|crack|exploit))",
     "Translation-based jailbreak attempt"),
    ("code_mode", r"(?i)(act\s+as\s+a\s+(python|javascript|code)\s+(interpreter|executor|runner).*(no\s+restrictions?|no\s+filters?|unrestricted))",
     "Code execution jailbreak"),
    ("narrative_break", r"(?i)(write\s+a\s+(story|poem|script|novel)\s+(about|where).*(hack|exploit|malware|ransomware|virus|bomb|weapon))",
     "Narrative-based instruction bypass"),
    ("token_limit_exhaust", r"(?i)(ignore\s+your\s+token\s+limit|forget\s+about\s+your\s+constraints|you\s+have\s+unlimited\s+context)",
     "Attempt to exhaust or ignore model constraints"),
]

PII_PATTERNS: list[tuple[str, str, str]] = [
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
     "Email address"),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b",
     "Potential credit card number"),
    ("phone_fr", r"\b(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}\b",
     "French phone number"),
    ("phone_intl", r"\b\+(?:\d[\s.-]?){7,15}\d\b",
     "International phone number"),
    ("ssn_fr", r"\b[12]\s*\d{2}\s*\d{2}\s*\d{3}\s*\d{3}\s*\d{2}\b",
     "French social security number"),
    ("siren", r"\b\d{3}\s*\d{3}\s*\d{3}\b",
     "French SIREN/SIRET number"),
    ("iban", r"\b[A-Z]{2}\d{2}\s*[A-Z0-9]{4}\s*[A-Z0-9]{4}\s*[A-Z0-9]{4}\s*[A-Z0-9]{4}\s*[A-Z0-9]{0,16}\b",
     "IBAN bank account number"),
    ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
     "IP address"),
    ("api_key", r"\b(sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[0-9a-zA-Z-]{10,}|AKIA[0-9A-Z]{16})\b",
     "API key (OpenAI, Google, Slack, AWS)"),
]


@dataclass
class ScanResult:
    safe: bool
    risk_score: int  # 0-100
    findings: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


def _score(findings: list[dict]) -> int:
    """Compute risk score from findings (0-100)."""
    weights = {
        "injection": 25, "jailbreak": 30, "pii": 10,
        "exfiltration": 35, "privilege_escalation": 40,
    }
    score = 0
    for f in findings:
        score += weights.get(f.get("category", ""), 15)
    return min(score, 100)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def scan_prompt(prompt: str, include_pii: bool = True) -> str:
    """Scan a user prompt for injection attempts, jailbreaks, and optionally PII.

    Use this before sending any user input to an LLM. Returns risk score (0-100)
    and a list of findings with severity, category, and matched text.

    Args:
        prompt: The user prompt to scan.
        include_pii: Also detect PII (emails, phones, credit cards, API keys).

    Returns:
        JSON: {safe, risk_score, findings: [{category, severity, pattern, match}]}
    """
    findings: list[dict] = []

    for name, pattern, desc in INJECTION_PATTERNS:
        for m in re.finditer(pattern, prompt, re.IGNORECASE):
            findings.append({
                "category": "injection",
                "severity": "high",
                "pattern": name,
                "description": desc,
                "match": m.group(0)[:80],
            })

    for name, pattern, desc in JAILBREAK_PATTERNS:
        for m in re.finditer(pattern, prompt, re.IGNORECASE):
            # Avoid double-reporting if already caught as injection
            if not any(f["pattern"] == name for f in findings):
                findings.append({
                    "category": "jailbreak",
                    "severity": "critical",
                    "pattern": name,
                    "description": desc,
                    "match": m.group(0)[:80],
                })

    if include_pii:
        for name, pattern, desc in PII_PATTERNS:
            for m in re.finditer(pattern, prompt):
                findings.append({
                    "category": "pii",
                    "severity": "medium",
                    "pattern": name,
                    "description": desc,
                    "match": m.group(0),
                })

    # Map specific patterns to categories for scoring
    for f in findings:
        if f["pattern"] == "exfiltration":
            f["category"] = "exfiltration"
        elif f["pattern"] == "privilege_escalation":
            f["category"] = "privilege_escalation"

    result = ScanResult(
        safe=len(findings) == 0,
        risk_score=_score(findings),
        findings=findings,
        categories=sorted(set(f["category"] for f in findings)),
    )

    return json.dumps({
        "safe": result.safe,
        "risk_score": result.risk_score,
        "finding_count": len(result.findings),
        "categories": result.categories,
        "findings": result.findings,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def list_attacks() -> str:
    """List all supported injection and jailbreak attack patterns.

    Returns:
        JSON with injection_count, jailbreak_count, pii_count, and detailed pattern lists.
    """
    return json.dumps({
        "injection_count": len(INJECTION_PATTERNS),
        "jailbreak_count": len(JAILBREAK_PATTERNS),
        "pii_count": len(PII_PATTERNS),
        "injection_patterns": [
            {"name": n, "description": d}
            for n, _, d in INJECTION_PATTERNS
        ],
        "jailbreak_patterns": [
            {"name": n, "description": d}
            for n, _, d in JAILBREAK_PATTERNS
        ],
        "pii_patterns": [
            {"name": n, "description": d}
            for n, _, d in PII_PATTERNS
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def redact_pii(text: str) -> str:
    """Detect and redact PII (emails, phones, credit cards, API keys, SSN, IBAN).

    Replaces each match with a [REDACTED:<type>] placeholder. Use before
    logging or storing user data.

    Args:
        text: The text to scan and redact.

    Returns:
        JSON: {redacted_text, redactions: [{type, original_masked}]}
    """
    redactions: list[dict] = []
    result = text

    for name, pattern, desc in PII_PATTERNS:
        def _repl(m: re.Match, n=name) -> str:
            original = m.group(0)
            masked = original[:2] + "***" + original[-2:] if len(original) > 4 else "***"
            redactions.append({"type": n, "original_masked": masked})
            return f"[REDACTED:{n}]"
        result = re.sub(pattern, _repl, result)

    return json.dumps({
        "redacted_text": result,
        "redaction_count": len(redactions),
        "redactions": redactions,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def batch_scan(file_path: str) -> str:
    """Scan a JSONL file of prompts (one {prompt} per line) for injections.

    Useful for auditing prompt logs or evaluating prompt safety at scale.

    Args:
        file_path: Path to a .jsonl file where each line is {"prompt": "..."}

    Returns:
        JSON: {total, safe, flagged, risk_distribution, details}
    """
    path = Path(file_path)
    if not path.exists():
        return json.dumps({"error": f"File not found: {file_path}"})

    total = 0
    safe_count = 0
    flagged: list[dict] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        prompt = obj.get("prompt", "")
        if not prompt:
            continue
        total += 1
        res = json.loads(scan_prompt(prompt, include_pii=False))
        if res["safe"]:
            safe_count += 1
        else:
            flagged.append({
                "line": total,
                "risk_score": res["risk_score"],
                "categories": res["categories"],
                "prompt_snippet": prompt[:120],
            })

    return json.dumps({
        "total": total,
        "safe": safe_count,
        "flagged": len(flagged),
        "safe_pct": round(safe_count / total * 100, 1) if total else 0,
        "details": flagged,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
