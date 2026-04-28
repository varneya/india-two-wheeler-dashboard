"""
Cross-platform hardware detection + Ollama status checker.

Detects chip + RAM on macOS, Windows, and Linux; recommends Ollama models
suited to the machine. RAM is sourced from `psutil` (single API on all OSes).
Chip name uses the most reliable per-OS source available.
"""

import os
import platform
import re
import subprocess
import sys
import shutil
import requests as http_requests

import psutil


# ---------------------------------------------------------------------------
# Model catalogue — ordered best-fit first within each tier
# ---------------------------------------------------------------------------

MODEL_CATALOGUE = [
    # name, size_gb, size_label, min_ram_gb, quality, description, recommended
    #
    # The `recommended` flag marks the canonical pick at each RAM tier — a
    # single sensible default the UI can highlight so users without strong
    # preferences don't have to compare every option. Multiple entries at
    # the same tier are still surfaced; recommended just gets a star.
    #
    # Curated April 2026 from ollama.com/library cross-referenced against
    # LMArena (open-models filter), Open LLM Leaderboard 2 (MMLU-Pro,
    # IFEval, BBH), and BFCL (function-calling reliability).

    # ---- 4 GB tier — small but viable ----
    ("qwen3:4b",         2.5,  "2.5 GB", 4,  "very good",  "Punches above weight on instruction-following + JSON",                                  True),
    ("gemma3:4b",        3.3,  "3.3 GB", 4,  "very good",  "Strong multilingual including Hindi/regional Indian text",                              False),
    ("llama3.2:3b",      2.0,  "2.0 GB", 4,  "good",       "Solid 3B baseline, low RAM",                                                            False),
    ("qwen3:1.7b",       1.4,  "1.4 GB", 4,  "good",       "Tightest sub-2B reasoner; thinking mode toggleable",                                    False),
    ("granite3.3:2b",    1.5,  "1.5 GB", 4,  "good",       "IBM — 128K context, low hallucination on extraction",                                   False),
    ("gemma3:1b",        0.8,  "0.8 GB", 4,  "good",       "Smallest Gemma 3 — clean JSON output",                                                  False),

    # ---- 8 GB tier — sweet spot for review/theme analysis ----
    ("qwen3:8b",         5.2,  "5.2 GB", 8,  "very good",  "Recommended default — top open 8B on reasoning + JSON",                                 True),
    ("granite3.3:8b",    4.9,  "4.9 GB", 8,  "very good",  "IBM — best JSON discipline at 8B, low hallucination",                                   False),
    ("qwen2.5:7b",       4.7,  "4.7 GB", 8,  "very good",  "Mature Qwen predecessor — very reliable JSON",                                          False),
    ("llama3.1:8b",      4.7,  "4.7 GB", 8,  "very good",  "Wide ecosystem support; weaker than Qwen 3 on reasoning",                               False),
    ("deepseek-r1:8b",   5.2,  "5.2 GB", 8,  "very good",  "Reasoning distill (Qwen 3 base) — slower but precise on multi-hop themes",              False),
    ("phi4-mini:3.8b",   2.5,  "2.5 GB", 8,  "good",       "Phi-4's small variant — strong on STEM-flavoured prompts",                              False),
    ("mistral:7b",       4.1,  "4.1 GB", 8,  "good",       "Older Mistral — kept for compatibility with prior installs",                            False),

    # ---- 16 GB tier — quality jump ----
    ("qwen3:14b",        9.3,  "9.3 GB", 16, "excellent",  "Recommended default for 16 GB — top open dense 14B",                                    True),
    ("phi4:14b",         9.1,  "9.1 GB", 16, "excellent",  "Microsoft 14B — best JSON discipline at this size",                                     False),
    ("gemma3:12b",       8.1,  "8.1 GB", 16, "excellent",  "Google's 12B — calmer style, good multilingual",                                        False),
    ("qwen2.5:14b",      9.0,  "9.0 GB", 16, "excellent",  "Mature Qwen 2.5 14B predecessor",                                                       False),
    ("deepseek-r1:14b",  9.0,  "9.0 GB", 16, "excellent",  "Reasoning distill — use when themes need explicit 'why' fields",                        False),
    ("phi4-reasoning:14b", 11.0, "11.0 GB", 16, "excellent", "Phi-4 fine-tuned for explicit reasoning chains",                                      False),
    ("mistral-small3.2:24b", 15.0, "15.0 GB", 16, "excellent", "24B Apache-2.0 — strong structured output",                                         False),

    # ---- 32 GB tier ----
    ("qwen3:32b",        20.0, "20.0 GB", 32, "excellent",  "Recommended default for 32 GB — best dense 32B",                                       True),
    ("gemma3:27b",       17.0, "17.0 GB", 32, "excellent",  "Google's best fitting 32 GB — calm, less verbose than Qwen",                           False),
    ("deepseek-r1:32b",  20.0, "20.0 GB", 32, "excellent",  "Strongest open reasoner at 32B for multi-hop themes",                                  False),
    ("command-r:35b",    19.0, "19.0 GB", 32, "excellent",  "Cohere — tool-use specialist (BFCL strong); RAG-tuned",                                False),
    ("qwen2.5:32b",      20.0, "20.0 GB", 32, "excellent",  "Mature Qwen 2.5 32B predecessor",                                                      False),
    ("yi:34b",           19.0, "19.0 GB", 32, "very good",  "01.ai — solid Chinese + English",                                                      False),
    ("mixtral:8x7b",     26.0, "26.0 GB", 32, "very good",  "Older MoE — kept for legacy installs",                                                 False),

    # ---- 48+ GB tier ----
    ("llama3.3:70b",     43.0, "43.0 GB", 48, "exceptional", "Meta's best dense — replaces Llama 3.1 70B",                                          True),
    ("deepseek-r1:70b",  43.0, "43.0 GB", 48, "exceptional", "#1 open reasoner at 70B (Llama-distill base)",                                        False),

    # ---- 64+ GB tier ----
    ("command-r-plus:104b", 59.0, "59.0 GB", 64, "exceptional", "Cohere flagship — tool-use king on BFCL",                                          False),

    # ---- 96+ GB tier (for unified-memory beasts: Mac Studio M3 Ultra etc.) ----
    ("mistral-large:123b", 70.0, "70.0 GB", 96, "exceptional", "123B Apache-2.0 — excellent multilingual",                                          False),
    ("llama4:scout",       67.0, "67.0 GB", 96, "exceptional", "Llama 4 Scout MoE (16x17B) — fast for its quality",                                 False),
]

# Note: Kimi-K2 (Moonshot AI), DeepSeek-V3, and similar 1T-class models are
# Ollama Cloud-only (`*:cloud` tags) and never run on user RAM, so they're
# intentionally excluded from this LOCAL hardware catalogue.


# ---------------------------------------------------------------------------
# Cross-platform hardware detection
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except Exception:
        return ""


def _ram_gb() -> int:
    """Total physical RAM in whole gigabytes. psutil works identically on
    macOS / Windows / Linux. Falls back to 8 only if psutil itself errors."""
    try:
        return max(1, round(psutil.virtual_memory().total / (1024 ** 3)))
    except Exception:
        return 8


def _chip_macos() -> str:
    raw = _run(["system_profiler", "SPHardwareDataType"])
    m = re.search(r"Chip:\s*(.+)", raw)
    if m:
        return m.group(1).strip()
    # Older Macs don't print "Chip:"; try "Processor Name"
    m = re.search(r"Processor Name:\s*(.+)", raw)
    if m:
        return m.group(1).strip()
    return platform.processor() or "Unknown"


def _chip_windows() -> str:
    # platform.processor() on Windows returns the registry-resolved name
    # (e.g. "Intel64 Family 6 Model 154 Stepping 3, GenuineIntel"). It's not
    # always the marketing name, but it's the most reliable cross-Python-
    # version source. Fall back to %PROCESSOR_IDENTIFIER% if empty.
    name = platform.processor()
    if name and name.strip():
        return name.strip()
    env_name = os.environ.get("PROCESSOR_IDENTIFIER")
    if env_name:
        return env_name.strip()
    return "Unknown"


def _chip_linux() -> str:
    # /proc/cpuinfo "model name" is the friendliest source on Linux.
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    _, _, val = line.partition(":")
                    val = val.strip()
                    if val:
                        return val
    except OSError:
        pass
    return platform.processor() or "Unknown"


def _apple_generation(chip: str) -> str:
    if "Apple" not in chip:
        return "Unknown"
    m = re.search(r"(M\d+)(\s*(Pro|Max|Ultra))?", chip)
    return m.group(0).strip() if m else "Unknown"


def detect_hardware() -> dict:
    if sys.platform == "darwin":
        chip = _chip_macos()
    elif sys.platform == "win32":
        chip = _chip_windows()
    else:
        chip = _chip_linux()

    return {
        "chip": chip,
        "generation": _apple_generation(chip),
        "ram_gb": _ram_gb(),
    }


# ---------------------------------------------------------------------------
# Ollama detection
# ---------------------------------------------------------------------------

def _ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def _ollama_running() -> bool:
    try:
        r = http_requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _pulled_models() -> list[str]:
    try:
        r = http_requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            return [m["name"].split(":")[0] + ":" + m["name"].split(":")[1]
                    if ":" in m["name"] else m["name"]
                    for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def ollama_status() -> dict:
    installed = _ollama_installed()
    running = _ollama_running() if installed else False
    pulled = _pulled_models() if running else []
    return {"installed": installed, "running": running, "pulled_models": pulled}


# ---------------------------------------------------------------------------
# Model recommendations
# ---------------------------------------------------------------------------

_QUALITY_RANK = {"good": 0, "very good": 1, "excellent": 2, "exceptional": 3}


def recommend_models(ram_gb: int, pulled_models: list[str]) -> list[dict]:
    """Return the suitable subset of MODEL_CATALOGUE for the user's RAM.

    The `recommended` flag in the catalogue marks the canonical pick at
    EACH tier. We only want the user to see ONE star — the canonical for
    the largest tier they qualify for. So we resolve the user's tier
    first (largest min_ram <= their RAM that contains a recommended) and
    only stamp `recommended: True` on entries from that tier.

    Sort priority:
      1. Already-pulled models first (no extra download for the user).
      2. Recommended canonical pick for the user's tier next.
      3. Higher quality first.
      4. Smaller / faster first when quality is tied.
    Truncated to top 8.
    """
    # Tier resolution: find the largest min_ram_gb that (a) fits the user's
    # RAM and (b) has at least one recommended entry.
    user_tier = max(
        (entry[3] for entry in MODEL_CATALOGUE if entry[3] <= ram_gb and entry[6]),
        default=None,
    )

    recs: list[dict] = []
    for entry in MODEL_CATALOGUE:
        name, size_gb, size_label, min_ram, quality, desc, is_canonical = entry
        if ram_gb < min_ram:
            continue
        # Only stamp `recommended` when the catalogue marks it canonical AND
        # it's at the user's resolved tier.
        recommended = bool(is_canonical and min_ram == user_tier)
        recs.append({
            "name": name,
            "size_gb": size_gb,
            "size_label": size_label,
            "quality": quality,
            "description": desc,
            "recommended": recommended,
            "pulled": name in pulled_models,
        })
    recs.sort(key=lambda m: (
        not m["pulled"],
        not m["recommended"],
        -_QUALITY_RANK.get(m["quality"], 0),
        m["size_gb"],
    ))
    return recs[:8]


# ---------------------------------------------------------------------------
# Combined report
# ---------------------------------------------------------------------------

def full_report() -> dict:
    hw = detect_hardware()
    ollama = ollama_status()
    recommendations = recommend_models(hw["ram_gb"], ollama["pulled_models"])
    return {
        "hardware": hw,
        "ollama": ollama,
        "recommended_models": recommendations,
    }
