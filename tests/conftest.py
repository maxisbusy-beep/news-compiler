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


@pytest.fixture
def fakes():
    return {"translate_fn": fake_translate, "embed_fn": fake_embed}


requires_models = pytest.mark.skipif(
    os.environ.get("NC_MODEL_TESTS") != "1",
    reason="real-model tests run in CI (set NC_MODEL_TESTS=1)",
)
