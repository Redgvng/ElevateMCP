# mcp-servers/gateway/_registry.py
"""Static registry: which functions each server exports, and which names conflict."""
from __future__ import annotations

TOOLS: dict[str, list[str]] = {
    "multiedit":       ["multi_edit", "multi_file_edit"],
    "semantic-search": ["index", "query", "list_indexes"],
    "git":             ["log", "diff", "blame", "find_commits_touching",
                        "branches", "status", "show"],
    "test-runner":     ["run", "list_tests"],
    "sql":             ["query", "tables", "describe", "explain"],
    "diff-apply":      ["parse", "dry_run", "apply"],
    "browser-inspect": ["screenshot", "dom", "console", "network",
                        "eval_js", "click_and_capture"],
    "secret-scan":     ["status", "scan_staged", "scan_diff",
                        "scan_history", "scan_file", "add_pattern"],
    "env-doctor":      ["check", "diff", "required", "template_gen"],
    "cve-search":      ["cve_status", "search_cve", "get_cve",
                        "stack_audit", "web_attack_surface", "sync"],
}

# Tools whose names collide across servers
RENAMES: dict[str, dict[str, str]] = {
    "semantic-search": {"query":  "ss_query"},
    "sql":             {"query":  "sql_query"},
    "git":             {"status": "git_status", "diff": "git_diff"},
    "secret-scan":     {"status": "scan_status"},
    "env-doctor":      {"diff":   "env_diff",   "check": "env_check"},
}
