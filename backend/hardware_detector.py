"""
Mac hardware detection + Ollama status checker.
Detects chip, RAM, recommends Ollama models suited to the machine.
"""

import re
import subprocess
import json
import shutil
import requests as http_requests


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
# Mac hardware detection
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except Exception:
        return ""


def detect_hardware() -> dict:
    raw = _run(["system_profiler", "SPHardwareDataType"])

    chip = "Unknown"
    ram_gb = 8

    chip_match = re.search(r"Chip:\s*(.+)", raw)
    if chip_match:
        chip = chip_match.group(1).strip()

    ram_match = re.search(r"Memory:\s*(\d+)\s*GB", raw)
    if ram_match:
        ram_gb = int(ram_match.group(1))

    # Determine Apple Silicon generation for display
    generation = "Unknown"
    if "Apple" in chip:
        gen_match = re.search(r"(M\d+)(\s*(Pro|Max|Ultra))?", chip)
        if gen_match:
            generation = gen_match.group(0).strip()

    return {"chip": chip, "generation": generation, "ram_gb": ram_gb}


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
