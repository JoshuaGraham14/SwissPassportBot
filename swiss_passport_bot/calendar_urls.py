from __future__ import annotations

import re


def sanitize_url(url: str) -> str:
    return re.sub(r"(token=)[^&#;]+", r"\1***", url)
