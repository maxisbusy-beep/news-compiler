import hashlib
import os
import re

import numpy as np
import pytest

DIM = 256


def fake_translate(lang, titles):
    """Stand-in translator: tags the text so tests can see it ran."""
    return [f"[{lang}] {t}" for t in titles]


def fake_embed(texts):
    """Deterministic bag-of-words hashing embedder (no model needed)."""
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for row, t in enumerate(texts):
        for w in re.findall(r"\w+", t.lower()):
            if len(w) < 3 or w in {"the", "and", "for", "with"}:
                continue
            h = int(hashlib.md5(w.encode()).hexdigest(), 16)
            out[row, h % DIM] += 1.0
    return out


def fake_llm(prompt):
    """Stand-in model: keeps every item and echoes the first headline."""
    lines = [l for l in prompt.splitlines() if l.startswith("[")]
    first = lines[0].split("] ", 1)[1].split(" | ")[0] if lines else "Nothing"
    import json as _json
    return _json.dumps({"belongs": list(range(len(lines))), "headline": first,
                        "summary": "", "region": "global"})


@pytest.fixture
def fakes():
    return {"translate_fn": fake_translate, "embed_fn": fake_embed, "llm_fn": fake_llm}


requires_models = pytest.mark.skipif(
    os.environ.get("NC_MODEL_TESTS") != "1",
    reason="real-model tests run in CI (set NC_MODEL_TESTS=1)",
)
