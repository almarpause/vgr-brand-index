"""Project configuration — settings.json + resolved paths.

Secrets never live here: SMTP is read from an external, git-ignored ini (reused
from the Zara parser) and/or environment variables. This module only resolves
the settings file and turns relative paths into absolute ones.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "recipients": [],
    "top_n": 500,
    "shard_count": 28,
    "do_trends": True,
    "subject_prefix": "VGR Brand Score",
    "smtp_ini": "",
}


def load_settings() -> dict:
    cfg = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        cfg.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    # resolve the external SMTP ini path relative to the project root
    ini = cfg.get("smtp_ini") or ""
    if ini:
        p = Path(ini)
        cfg["smtp_ini"] = str(p if p.is_absolute() else (ROOT / p).resolve())
    return cfg
