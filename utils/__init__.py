import re
import unicodedata


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("　", " ").replace(" ", " ")
    s = s.replace("​", "").replace("﻿", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s
