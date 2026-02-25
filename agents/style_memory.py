"""
Style Memory — Persistent learning system for news story patterns.

Accumulates story structures, framing styles, headline templates, and
topic distributions across scrape sessions. Grows over time to provide
an increasingly rich and diverse pool of patterns for the writer.
"""

import json
import os
import re
from datetime import datetime, timedelta

STYLE_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "style_library.json"
)

MAX_HEADLINE_TEMPLATES = 200
MAX_EXAMPLES_PER_STYLE = 20
MAX_REGISTER_HISTORY = 30  # days


def _empty_library():
    """Return a fresh empty style library."""
    return {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "total_scrapes": 0,
        "framing_styles": {},
        "headline_templates": [],
        "topic_distribution": {},
        "conflict_type_frequency": {},
        "register_history": [],
    }


def load_style_library():
    """Load the style library from disk, creating a fresh one if missing."""
    if not os.path.exists(STYLE_LIBRARY_PATH):
        return _empty_library()
    try:
        with open(STYLE_LIBRARY_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _empty_library()


def save_style_library(library):
    """Write the style library to disk."""
    library["last_updated"] = datetime.now().isoformat()
    with open(STYLE_LIBRARY_PATH, "w") as f:
        json.dump(library, f, indent=2)


def update_from_scrape(library, blueprints, register, topic_counts):
    """
    Merge new scrape data into the persistent library.

    - Increment framing style counts, add new example headlines
    - Extract headline templates from blueprints
    - Update topic and conflict type distributions (rolling average)
    - Append register to history
    """
    library["total_scrapes"] = library.get("total_scrapes", 0) + 1
    today = datetime.now().strftime("%Y-%m-%d")

    # ── Update framing styles ──
    framing_styles = library.get("framing_styles", {})
    for bp in blueprints:
        style = bp.get("framing_style", "development")
        if style not in framing_styles:
            framing_styles[style] = {"count": 0, "examples": []}
        framing_styles[style]["count"] += 1
        # Add headline as example (dedup, cap)
        headline = bp.get("headline_frame", "")
        examples = framing_styles[style]["examples"]
        if headline and headline not in examples:
            examples.append(headline)
            if len(examples) > MAX_EXAMPLES_PER_STYLE:
                examples.pop(0)  # Drop oldest
    library["framing_styles"] = framing_styles

    # ── Extract and store headline templates ──
    templates = library.get("headline_templates", [])
    existing_templates = {t["template"] for t in templates}

    for bp in blueprints:
        headline = bp.get("headline_frame", "")
        if not headline or len(headline) < 20:
            continue
        template = _templatize_headline(headline)
        if template and template not in existing_templates:
            templates.append({
                "template": template,
                "topic": bp.get("topic", ""),
                "times_seen": 1,
                "last_seen": today,
                "example": headline[:120],
            })
            existing_templates.add(template)
        elif template:
            # Increment times_seen for existing template
            for t in templates:
                if t["template"] == template:
                    t["times_seen"] = t.get("times_seen", 1) + 1
                    t["last_seen"] = today
                    break

    # Cap at max
    if len(templates) > MAX_HEADLINE_TEMPLATES:
        # Keep the most-seen and most-recent templates
        templates.sort(key=lambda t: (t.get("times_seen", 1), t.get("last_seen", "")), reverse=True)
        templates = templates[:MAX_HEADLINE_TEMPLATES]
    library["headline_templates"] = templates

    # ── Update topic distribution (rolling average) ──
    topic_dist = library.get("topic_distribution", {})
    total_topic_score = sum(topic_counts.values()) or 1
    for topic, count in topic_counts.items():
        new_ratio = count / total_topic_score
        if topic in topic_dist:
            # Blend: 70% existing, 30% new observation
            topic_dist[topic] = round(0.7 * topic_dist[topic] + 0.3 * new_ratio, 4)
        else:
            topic_dist[topic] = round(new_ratio, 4)
    library["topic_distribution"] = topic_dist

    # ── Update conflict type frequency ──
    conflict_freq = library.get("conflict_type_frequency", {})
    for bp in blueprints:
        ctype = bp.get("conflict_type", "development")
        conflict_freq[ctype] = conflict_freq.get(ctype, 0) + 1
    # Normalize to proportions
    total_conflicts = sum(conflict_freq.values()) or 1
    for ctype in conflict_freq:
        conflict_freq[ctype] = round(conflict_freq[ctype] / total_conflicts, 4)
    library["conflict_type_frequency"] = conflict_freq

    # ── Append register history (rolling 30 days) ──
    reg_history = library.get("register_history", [])
    reg_history.append({"date": today, "register": register})
    # Keep only last 30 days
    cutoff = (datetime.now() - timedelta(days=MAX_REGISTER_HISTORY)).strftime("%Y-%m-%d")
    reg_history = [r for r in reg_history if r.get("date", "") >= cutoff]
    library["register_history"] = reg_history

    return library


def _templatize_headline(headline):
    """
    Convert an anonymized headline into a reusable template.

    'Federal aviation regulator orders emergency inspections of regional carrier fleet'
    -> '[Agency] orders emergency [action] of [target]'
    """
    if not headline or len(headline) < 15:
        return None

    result = headline

    # Replace numbers/dollar amounts with placeholders
    result = re.sub(r'\$[\d,.]+\s*(?:billion|million|trillion|thousand|B|M|T)?', '[Amount]', result, flags=re.IGNORECASE)
    result = re.sub(r'\d+(?:\.\d+)?%', '[Percent]', result)
    result = re.sub(r'\b\d{2,}\b', '[Number]', result)

    # Replace institutional role phrases with placeholders
    role_patterns = [
        (r'\b(?:federal|state|local)\s+(?:agency|regulator|authority|commission|bureau|department)\b',
         '[Agency]'),
        (r'\b(?:a (?:senior|top|prominent|leading)\s+(?:official|lawmaker|executive|diplomat))\b',
         '[Official]'),
        (r'\b(?:a major\s+(?:corporation|company|manufacturer|bank|firm|insurer|automaker|'
         r'technology company|aerospace manufacturer|energy company|pharmaceutical company|'
         r'defense contractor|retail chain|streaming service|social media company|'
         r'online retail corporation|software corporation|electric vehicle maker|'
         r'entertainment company|social media conglomerate|social media platform|'
         r'AI company|healthcare corporation|technology conglomerate|investment bank|'
         r'oil corporation|health insurer))\b',
         '[Organization]'),
        (r'\b(?:a state governor)\b', '[Governor]'),
        (r'\b(?:the President|the Vice President|the former President)\b', '[Leader]'),
    ]

    for pattern, placeholder in role_patterns:
        result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)

    # Don't return if template is too similar to original (not enough abstracted)
    placeholders = len(re.findall(r'\[(?:Amount|Percent|Number|Agency|Official|Organization|Governor|Leader)\]', result))
    if placeholders == 0:
        # Still useful as a structural template even without placeholders
        pass

    # Clean up
    result = re.sub(r'\s+', ' ', result).strip()

    # Skip if too short after processing
    if len(result) < 10:
        return None

    return result


def get_style_context_for_writer(library, topic=None):
    """
    Build a text block summarizing accumulated style knowledge
    for injection into the writer prompt.

    Returns ~200 word context string with:
    - Relevant headline templates
    - Top framing styles with examples
    - Current topic/conflict distributions
    """
    if library.get("total_scrapes", 0) == 0:
        return ""

    lines = []

    # ── Headline templates ──
    templates = library.get("headline_templates", [])
    if templates:
        # Filter by topic if given, otherwise pick diverse set
        if topic:
            relevant = [t for t in templates if t.get("topic") == topic]
        else:
            relevant = templates

        # Sort by times_seen (most common patterns first)
        relevant.sort(key=lambda t: t.get("times_seen", 1), reverse=True)

        if relevant:
            lines.append("HEADLINE PATTERNS COMMONLY SEEN IN REAL NEWS:")
            for t in relevant[:5]:
                lines.append(f"  - {t['template']}  (topic: {t.get('topic', '?')}, "
                             f"seen {t.get('times_seen', 1)}x)")

    # ── Framing style summary ──
    framing = library.get("framing_styles", {})
    if framing:
        sorted_styles = sorted(framing.items(), key=lambda x: x[1].get("count", 0), reverse=True)
        top_styles = sorted_styles[:4]
        if top_styles:
            lines.append("\nMOST COMMON STORY FRAMINGS:")
            for style, data in top_styles:
                count = data.get("count", 0)
                example = data.get("examples", [""])[0][:80] if data.get("examples") else ""
                lines.append(f"  - {style} ({count} stories). E.g.: \"{example}\"")

    # ── Register trend ──
    reg_history = library.get("register_history", [])
    if len(reg_history) >= 3:
        recent = [r["register"] for r in reg_history[-5:]]
        trend = max(set(recent), key=recent.count)
        lines.append(f"\nRECENT NEWS MOOD: mostly {trend} (last {len(recent)} scrapes)")

    # ── Topic distribution ──
    topic_dist = library.get("topic_distribution", {})
    if topic_dist:
        sorted_topics = sorted(topic_dist.items(), key=lambda x: x[1], reverse=True)
        top = [f"{t[0]} ({t[1]:.0%})" for t in sorted_topics[:5] if t[1] > 0.05]
        if top:
            lines.append(f"\nTOP REAL-NEWS TOPICS: {', '.join(top)}")

    return "\n".join(lines)
