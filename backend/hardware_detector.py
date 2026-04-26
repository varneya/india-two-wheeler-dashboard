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
    # name, size_gb, size_label, min_ram_gb, quality, description
    ("phi3:mini",      2.2,  "2.2 GB", 4,  "good",      "Fastest, lowest RAM"),
    ("llama3.2:3b",    2.0,  "2.0 GB", 4,  "good",      "Fast and capable"),
    ("mistral:7b",     4.1,  "4.1 GB", 8,  "very good", "Great for text analysis"),
    ("llama3.2:8b",    4.7,  "4.7 GB", 8,  "very good", "Best balance of speed & quality"),
    ("llama3.1:8b",    4.7,  "4.7 GB", 8,  "very good", "Strong reasoning"),
    ("mixtral:8x7b",  26.0, "26.0 GB", 32, "excellent", "Very high quality"),
    ("llama3.1:70b",  40.0, "40.0 GB", 48, "exceptional","Best available locally"),
]


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

def recommend_models(ram_gb: int, pulled_models: list[str]) -> list[dict]:
    recs = []
    for name, size_gb, size_label, min_ram, quality, desc in MODEL_CATALOGUE:
        if ram_gb >= min_ram:
            recs.append({
                "name": name,
                "size_gb": size_gb,
                "size_label": size_label,
                "quality": quality,
                "description": desc,
                "pulled": name in pulled_models,
            })
    # Put already-pulled models first, then sort by size ascending
    recs.sort(key=lambda m: (not m["pulled"], m["size_gb"]))
    return recs[:5]  # top 5 suitable models


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
