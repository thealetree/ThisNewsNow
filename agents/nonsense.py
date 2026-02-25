"""
Nonsense Injector — Markov chain word fragment generator
based on the Mustard & Milk corpus by Van Sanders.

Occasionally injects surreal 2-4 word fragments into news scripts,
creating subtle double-take moments for attentive readers. The
fragment replaces an equal number of words mid-script so the word
count stays stable.

Settings (config.yaml → dials.nonsense):
    enabled: true/false
    injection_chance: 0.15  (15% of stories get a fragment)
    min_fragment: 2
    max_fragment: 4
    temperature: 1.0
"""

import json
import math
import os
import random
import re

_model = None
_model_path = os.path.join(os.path.dirname(__file__), "markov_model.json")


def _load_model():
    """Lazy-load the Markov chain model."""
    global _model
    if _model is None:
        with open(_model_path) as f:
            _model = json.load(f)
    return _model


def _pick_from_options(options, temperature=1.0):
    """Pick a word from [word, frequency] pairs with temperature sampling."""
    if not options:
        return None
    if temperature == 1.0:
        weights = [o[1] for o in options]
    else:
        weights = [math.pow(o[1], 1.0 / temperature) for o in options]
    total = sum(weights)
    r = random.random() * total
    for i, w in enumerate(weights):
        r -= w
        if r <= 0:
            return options[i][0]
    return options[-1][0]


def _pick_weighted(items, weights, temperature=1.0):
    """Pick from items list using weight list with temperature."""
    if temperature == 1.0:
        adj = list(weights)
    else:
        adj = [math.pow(w, 1.0 / temperature) for w in weights]
    total = sum(adj)
    r = random.random() * total
    for i, w in enumerate(adj):
        r -= w
        if r <= 0:
            return items[i]
    return items[-1]


def _fix_contractions(text):
    """Rejoin contractions that were split during original tokenization."""
    fixes = [
        (r"\bi m\b", "i'm"),
        (r"\bdon t\b", "don't"),
        (r"\bcan t\b", "can't"),
        (r"\bwon t\b", "won't"),
        (r"\bdoesn t\b", "doesn't"),
        (r"\bisn t\b", "isn't"),
        (r"\bdidn t\b", "didn't"),
        (r"\bwasn t\b", "wasn't"),
        (r"\baren t\b", "aren't"),
        (r"\bweren t\b", "weren't"),
        (r"\bshouldn t\b", "shouldn't"),
        (r"\bcouldn t\b", "couldn't"),
        (r"\bwouldn t\b", "wouldn't"),
        (r"\bi ve\b", "i've"),
        (r"\bi ll\b", "i'll"),
        (r"\bi d\b", "i'd"),
        (r"\bwe re\b", "we're"),
        (r"\bthey re\b", "they're"),
        (r"\byou re\b", "you're"),
        (r"\bit s\b", "it's"),
        (r"\bthat s\b", "that's"),
        (r"\bwhat s\b", "what's"),
        (r"\bthere s\b", "there's"),
        (r"\bhere s\b", "here's"),
    ]
    for pattern, replacement in fixes:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def generate_fragment(min_words=2, max_words=4, temperature=1.0):
    """
    Generate a short Markov chain word fragment.
    Returns a lowercase string of 2-4 words with no end punctuation.
    """
    model = _load_model()
    target_len = random.randint(min_words, max_words)

    # Pick a weighted-random starter pair
    starters = model["s"]
    starter_weights = model["sw"]
    starter = _pick_weighted(starters, starter_weights, temperature)

    words = list(starter)

    # Extend with chain lookups
    for _ in range(target_len - len(words)):
        key2 = f"{words[-2]}|{words[-1]}" if len(words) >= 2 else None
        next_word = None

        if key2 and key2 in model["c2"]:
            next_word = _pick_from_options(model["c2"][key2], temperature)
        elif words[-1] in model["c1"]:
            next_word = _pick_from_options(model["c1"][words[-1]], temperature)

        if not next_word:
            break

        # Strip sentence-ending punctuation so it flows mid-sentence
        clean = next_word.rstrip(".!?…")
        if clean:
            words.append(clean)
        else:
            break

    fragment = " ".join(words[:target_len]).lower()
    fragment = _fix_contractions(fragment)
    return fragment


def inject_nonsense(script_text, config):
    """
    Possibly inject a nonsense fragment into a news script.

    Reads settings from config['dials']['nonsense'].
    Replaces N consecutive spoken words with N Markov-generated words
    so word count is preserved.

    Returns:
        (modified_script, injected: bool, fragment: str or None)
    """
    settings = config.get("dials", {}).get("nonsense", {})

    if not settings.get("enabled", False):
        return script_text, False, None

    chance = settings.get("injection_chance", 0.15)

    # Roll the dice for this story
    if random.random() > chance:
        return script_text, False, None

    min_frag = settings.get("min_fragment", 2)
    max_frag = settings.get("max_fragment", 4)
    temperature = settings.get("temperature", 1.0)

    # Generate the fragment
    fragment = generate_fragment(min_frag, max_frag, temperature)
    frag_words = fragment.split()
    frag_len = len(frag_words)

    # Tokenise script, keeping [TAG: ...] blocks as single tokens
    tokens = re.findall(r'\[[A-Z_-]+:\s*[^\]]+\]|\S+', script_text)

    # Identify indices of spoken (non-tag) tokens
    spoken_idx = [i for i, t in enumerate(tokens) if not t.startswith('[')]

    # Must have enough room: skip first 6 and last 6 spoken words
    margin = 6
    if len(spoken_idx) < margin * 2 + frag_len:
        return script_text, False, None

    # Eligible injection zone
    lo = margin
    hi = len(spoken_idx) - margin - frag_len
    if hi <= lo:
        return script_text, False, None

    inject_at = random.randint(lo, hi)

    # Replace frag_len spoken words starting at inject_at
    positions = spoken_idx[inject_at : inject_at + frag_len]
    for j, pos in enumerate(positions):
        if j < len(frag_words):
            tokens[pos] = frag_words[j]

    modified = " ".join(tokens)
    return modified, True, fragment
