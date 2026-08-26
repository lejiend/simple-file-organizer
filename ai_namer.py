"""
ai_namer.py

Optional AI-powered renaming step for the simple file organizer.

Given a file, this module tries to read a bit of its content (plain text,
PDF, DOCX, or — for images — the image itself) and asks an LLM via
OpenRouter (https://openrouter.ai) to suggest a short, descriptive
filename based on what the file actually contains, instead of whatever
generic name it arrived with (e.g. "IMG_4821.png", "download (3).pdf").

The model is specifically prompted to work out the document's PURPOSE,
the PARTY involved, and the PERIOD/DATE (e.g., month/year), combining
them as "Purpose - Party - Period" (e.g., "Payment Receipt - Ruang Kerja Damai - Aug 2026").

Design goals:
- Never block or crash a sort. Any failure (missing API key, no network,
  unsupported file type, bad/empty response, rate limit, etc.) results in
  `suggest_filename()` returning None, and the caller falls back to the
  file's original name.
- Zero cost for file types we can't meaningfully read (archives,
  installers, audio, video, etc.) — we simply never call the API for
  those, since content extraction returns nothing for them.
- Keep the network call and the extraction logic separate so both are
  easy to test/extend independently.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("organizer.ai_namer")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# File types we know how to pull readable content out of.
TEXT_EXTENSIONS = {
    "txt", "md", "csv", "tsv", "json", "yml", "yaml", "log", "rtf",
    "py", "js", "ts", "jsx", "tsx", "html", "css", "java", "c", "cpp",
    "sh", "rb", "go", "php", "swift",
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
PDF_EXTENSIONS = {"pdf"}
DOCX_EXTENSIONS = {"docx"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS

_ILLEGAL_CHARS = re.compile(r'[\/:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_MAX_IMAGE_BYTES = 5_000_000  # skip huge images rather than send megabytes of base64


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """Strip anything that isn't safe in a filename and cap the length."""
    name = name.strip().strip(".").strip('"').strip("'")
    name = _ILLEGAL_CHARS.sub("", name)
    name = _WHITESPACE.sub(" ", name).strip()
    return name[:max_length].strip()


def _extract_text(path: Path, max_chars: int) -> Optional[str]:
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext in TEXT_EXTENSIONS:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(max_chars)
            return text if text.strip() else None

        if ext in PDF_EXTENSIONS:
            try:
                from pypdf import PdfReader
            except ImportError:
                logger.info("pypdf not installed; skipping AI rename for %s", path.name)
                return None
            reader = PdfReader(str(path))
            chunks = []
            total = 0
            for page in reader.pages[:5]:
                page_text = page.extract_text() or ""
                chunks.append(page_text)
                total += len(page_text)
                if total >= max_chars:
                    break
            text = "\n".join(chunks)[:max_chars]
            return text if text.strip() else None

        if ext in DOCX_EXTENSIONS:
            try:
                import docx
            except ImportError:
                logger.info("python-docx not installed; skipping AI rename for %s", path.name)
                return None
            document = docx.Document(str(path))
            text = "\n".join(p.text for p in document.paragraphs)[:max_chars]
            return text if text.strip() else None

    except Exception as exc:  # noqa: BLE001 - extraction must never blow up the run
        logger.warning("Could not extract text from %s: %s", path.name, exc)
        return None

    return None


def _encode_image(path: Path) -> Optional[str]:
    ext = path.suffix.lower().lstrip(".")
    try:
        if path.stat().st_size > _MAX_IMAGE_BYTES:
            logger.info("Skipping AI rename for %s: image too large", path.name)
            return None
        data = path.read_bytes()
        mime = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
        }.get(ext, "application/octet-stream")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read image %s: %s", path.name, exc)
        return None


def suggest_filename(path: Path, settings, api_key: Optional[str]) -> Optional[str]:
    """
    Ask the configured OpenRouter model for a short descriptive filename
    (no extension, no path) for `path`, based on its content.

    Returns None (never raises) if the API key is missing, the file type
    isn't one we can read, content extraction failed, or the API call
    failed for any reason. Callers should treat None as "keep the
    original name".
    """
    if not api_key:
        return None

    ext = path.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXTENSIONS:
        return None

    image_data_url = None
    text_content = None

    if ext in IMAGE_EXTENSIONS:
        image_data_url = _encode_image(path)
        if image_data_url is None:
            return None
    else:
        text_content = _extract_text(path, settings.ai_max_content_chars)
        if not text_content:
            return None

    instruction = (
       "You are naming a file for a personal computer folder. Read its "
        "content and work out three things: (1) the PURPOSE of the document "
        "— what it is, e.g. invoice, receipt, contract/agreement, transfer "
        "confirmation, bank statement, report; (2) the other PARTY involved, "
        "if there is one — the person, client, company, or recipient/sender "
        "it's to or from; and (3) the PERIOD or DATE, if applicable — e.g. "
        "month and year (e.g. 'Aug 2026', 'Jul 2026'), date (e.g. '2026-08-15'), "
        "or billing period. "
        "Combine them into the filename as 'Purpose - Party - Period', e.g. "
        "'Payment Receipt - Ruang Kerja Damai - Aug 2026', "
        "'Invoice - Cloud Services - Jul 2026', "
        "'Freelance Agreement - Threads Promotion - 2026'. "
        "If there is no specific party, use 'Purpose - Period'. "
        "If there is no date/period, fall back to 'Purpose - Party'. "
        "3-10 words total, no file extension, no quotes, no path, use "
        "spaces or hyphens only, no other special characters. "
        "Reply with ONLY the filename and nothing else.\n\n"
        f"Original filename: {path.name}\n"
    )

    if image_data_url:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction + "The file is the image below."},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }]
    else:
        messages = [{
            "role": "user",
            "content": instruction + f"File content (may be truncated):\n---\n{text_content}\n---",
        }]

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "model": settings.ai_model,
                "messages": messages,
                "max_tokens": 40,
                "temperature": 0.2,
            }),
            timeout=settings.ai_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        raw_name = payload["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - a failed AI call must never break a sort
        logger.warning("AI rename failed for %s: %s", path.name, exc)
        return None

    clean = sanitize_filename(raw_name)
    return clean or None
