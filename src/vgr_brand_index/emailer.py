"""Email the monthly report.

SMTP credentials are reused from the Zara parser's git-ignored email.ini (path in
settings.json), overridable by VBI_SMTP_* or ZARA_SMTP_* environment variables —
the same pattern as the polyamide-index pipeline. Nothing secret is stored in
this repo. A missing credential is reported and the send is skipped; it never
loses the already-built report.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from configparser import ConfigParser
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

from .config import load_settings
from .deltas import Deltas
from .report import month_label, _fmt_delta


def load_smtp(cfg: dict) -> dict:
    s = {"host": "", "port": "587", "user": "", "password": "", "from": ""}
    ini = Path(cfg.get("smtp_ini") or "")
    if ini and ini.exists():
        cp = ConfigParser()
        cp.read(ini, encoding="utf-8")
        for k in ("host", "port", "user", "password", "from"):
            if cp.has_option("smtp", k):
                s[k] = cp.get("smtp", k)
    env = os.environ
    for k, ev in (("host", "SMTP_HOST"), ("port", "SMTP_PORT"), ("user", "SMTP_USER"),
                  ("password", "SMTP_PASSWORD"), ("from", "SMTP_FROM")):
        s[k] = env.get(f"VBI_{ev}", env.get(f"ZARA_{ev}", s[k]))
    s["from"] = s["from"] or s["user"]
    s["password"] = s["password"].replace(" ", "")  # gmail app-password spaces
    return s


def render(top: pd.DataFrame, d: Deltas, prefix: str) -> tuple[str, str, str]:
    ml = month_label(d.month)
    lead = top.iloc[0]
    subject = f"{prefix} — {ml}: {lead['brand']} leads"

    def li(rows):
        return "".join(
            f"<li><b>{r.brand}</b> — index {r.index:.0f}"
            + (f" ({_fmt_delta(r.index_delta)})" if r.index_delta is not None else "")
            + "</li>"
            for r in rows
        )

    counts = top["tier"].value_counts()
    movers_html = ""
    if d.has_prior and d.top_risers:
        movers_html = f"<h3 style='font-family:Arial'>Biggest risers</h3><ul>{li(d.top_risers[:5])}</ul>"

    html = f"""<div style="font-family:Georgia,serif;color:#1A1A1A;max-width:640px">
      <p style="font-family:Arial;color:#C0110A;font-weight:bold;letter-spacing:1px">VGR · BRAND INDEX</p>
      <h2 style="margin:0 0 6px">{ml}</h2>
      <p><b>{lead['brand']}</b> leads the index at {lead['interest_index']:.0f}
      (top-5 average = 100). A tier {int(counts.get('A',0))}, B tier {int(counts.get('B',0))},
      C tier {int(counts.get('C',0))}.</p>
      {movers_html}
      <p style="font-family:Arial;font-size:12px;color:#5A6A7A">Full report attached (.docx).
      Sources: Wikipedia, GDELT, Google Trends, Wikidata. Not investment advice.</p>
    </div>"""
    text = (f"VGR Brand Index — {ml}\n{lead['brand']} leads at {lead['interest_index']:.0f} "
            f"(top-5=100). See attached report.")
    return subject, text, html


def send_report(docx_path: Path, top: pd.DataFrame, d: Deltas) -> int:
    cfg = load_settings()
    recipients = cfg.get("recipients") or []
    if not recipients:
        print("    [email] no recipients configured"); return 1
    smtp = load_smtp(cfg)
    missing = [k for k in ("host", "user", "password", "from") if not smtp.get(k)]
    if missing:
        print(f"    [email] missing SMTP settings: {missing}"); return 1

    subject, text, html = render(top, d, cfg.get("subject_prefix", "VGR Brand Index"))
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp["from"]
    msg["To"] = ", ".join(recipients)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)
    if docx_path.exists():
        part = MIMEApplication(docx_path.read_bytes(),
                               _subtype="vnd.openxmlformats-officedocument.wordprocessingml.document")
        part.add_header("Content-Disposition", "attachment", filename=docx_path.name)
        msg.attach(part)

    port = int(smtp["port"])
    if port == 465:
        with smtplib.SMTP_SSL(smtp["host"], port, context=ssl.create_default_context()) as srv:
            srv.login(smtp["user"], smtp["password"])
            srv.sendmail(smtp["from"], recipients, msg.as_string())
    else:
        with smtplib.SMTP(smtp["host"], port) as srv:
            srv.starttls(context=ssl.create_default_context())
            srv.login(smtp["user"], smtp["password"])
            srv.sendmail(smtp["from"], recipients, msg.as_string())
    print(f"    [email] sent to {len(recipients)} recipient(s)")
    return 0
