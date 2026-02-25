"""
Writer Agent — Generates deadpan, believable anchor scripts for This News Now.

Uses Claude API to produce 25-second broadcast scripts complete with
chyron tags and B-roll descriptions. All content is fictional but
designed to be indistinguishable from real local/national news.
"""

import anthropic
import json
import random
import re
import uuid


# Word count targets
MIN_WORDS = 60
MAX_WORDS = 75
MAX_RETRIES = 3


def generate_script(config, world_bible, news_context):
    """
    Generate a single anchor script using Claude.
    Retries if word count is outside 60-75 range.

    Returns a dict with:
        - script: full anchor script text
        - chyrons: list of chyron strings
        - broll_descriptions: list of B-roll shot descriptions
        - anchor: anchor name
        - estimated_seconds: ~25
        - topic: story topic category
        - story_id: unique ID
        - word_count: actual spoken word count
    """
    client = anthropic.Anthropic(api_key=config["apis"]["anthropic_key"])

    # Pick a random anchor
    anchor = random.choice(world_bible["anchors"])

    # Build world bible summary for context injection
    world_summary = _build_world_summary(world_bible)

    # Get operator dial settings
    dials = config.get("dials", {})
    tone = dials.get("tone", "concerned")
    topic_weights = dials.get("topic_weights", {})

    system_msg = """You are a television news script writer. You write extremely concise broadcast copy. Every word must earn its place. You never exceed the word count you are given. You write in plain text only — no markdown, no formatting, no character names as prefixes."""

    # Build story shapes block if available
    story_shapes = news_context.get("story_shapes", [])
    conflict_types = news_context.get("conflict_types", [])
    shapes_block = ""
    if story_shapes:
        shapes_block = "\n\nREAL-WORLD NEWS SHAPES (use these as inspiration for your FICTIONAL story — mirror the topic, conflict type, and stakes, but invent all details):\n"
        for shape in story_shapes[:4]:
            shapes_block += f"  - {shape}\n"
    if conflict_types:
        shapes_block += f"\nACTIVE CONFLICT TYPES in today's news: {', '.join(conflict_types)}"

    prompt = f"""Write a single anchor read for This News Now (TNN).

WORLD CONTEXT:
{world_summary}

NEWS REGISTER: {news_context.get('register', 'tense')}
TRENDING: {', '.join(news_context.get('trending_topics', ['politics', 'economy']))}
TONE: {tone}
TOPIC WEIGHTS: {json.dumps(topic_weights)}
{shapes_block}

HARD REQUIREMENTS:
- EXACTLY 60 to 75 spoken words. Not 76. Not 100. Count carefully.
- Tags like [CHYRON: ...] and [B-ROLL: ...] do NOT count toward the word limit.
- Cover ONE story. One angle. No pivoting to a second story.
- End with a natural anchor sign-off: a toss to break, a tease of what's ahead, or a simple "more on this as it develops" style line. Keep it under 10 words.

ANCHOR: {anchor['name']} ({anchor['gender']})

CONTENT RULES:
- Deadpan. No humor, no irony.
- You MAY use real US places, real federal agencies (EPA, FBI, FEMA, etc.), real political parties.
- All PEOPLE, COMPANIES, specific EVENTS, and QUOTES must be fictional.
- Use places and storylines from the world context, or invent fitting new ones.
- DRAW HEAVILY from the real-world news shapes above. Create stories on similar topics, with similar conflict types and stakes, set in similar geographic contexts. This makes your fiction feel adjacent to reality.
- One [CHYRON: text] tag and one [B-ROLL: description] tag, placed inline where they'd appear on screen.
- No markdown. No bold. No anchor name prefix. Just the spoken script with inline tags.

EXAMPLE of correct length (68 words):
Good evening. The Environmental Protection Agency confirmed tonight that water samples from three Toledo neighborhoods exceed federal lead thresholds by a significant margin. City Manager Greg Hess is pushing back, calling the findings preliminary, but state health officials have already issued a boil-water advisory for residents east of the Maumee River. FEMA resources have been requested. [CHYRON: TOLEDO WATER CRISIS DEEPENS] [B-ROLL: EPA crews collecting samples at residential homes] We'll have more after the break.

NOW WRITE YOUR SCRIPT:"""

    # Try up to MAX_RETRIES times to get a script within word count
    for attempt in range(MAX_RETRIES):
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=system_msg,
            messages=[{"role": "user", "content": prompt}],
        )

        script_text = message.content[0].text.strip()
        spoken_words = _count_spoken_words(script_text)

        if MIN_WORDS <= spoken_words <= MAX_WORDS:
            break
        elif attempt < MAX_RETRIES - 1:
            print(f"  Retry {attempt + 1}: got {spoken_words} words (need {MIN_WORDS}-{MAX_WORDS})")
            # Adjust prompt hint for retry
            if spoken_words > MAX_WORDS:
                prompt += f"\n\nYour previous attempt was {spoken_words} words. That is too long. Cut it down to 65 words maximum. Be ruthless — remove adjectives, combine sentences, shorten the sign-off."
            else:
                prompt += f"\n\nYour previous attempt was only {spoken_words} words. Add one more detail to reach at least {MIN_WORDS} words."
        else:
            print(f"  Warning: final attempt got {spoken_words} words (target {MIN_WORDS}-{MAX_WORDS})")

    # Nonsense injection (post-processing, after word count is validated)
    from agents.nonsense import inject_nonsense
    script_text, injected, fragment = inject_nonsense(script_text, config)
    if injected:
        print(f"  \u2726 Nonsense injected: '{fragment}'")

    # Parse chyrons and B-roll from the script
    chyrons = _extract_tags(script_text, "CHYRON")
    broll_descriptions = _extract_tags(script_text, "B-ROLL")

    # Determine topic from script content
    topic = _classify_topic(script_text, topic_weights)

    story_id = str(uuid.uuid4())[:8]

    script_data = {
        "script": script_text,
        "chyrons": chyrons,
        "broll_descriptions": broll_descriptions,
        "anchor": anchor["name"],
        "anchor_gender": anchor["gender"],
        "estimated_seconds": 25,
        "topic": topic,
        "story_id": story_id,
        "word_count": spoken_words,
        "nonsense_injected": injected,
    }

    print(f"  Script generated: [{topic}] {spoken_words}w — {chyrons[0] if chyrons else 'No chyron'}")
    return script_data


def _count_spoken_words(script_text):
    """Count only spoken words, excluding [TAG: ...] content."""
    cleaned = re.sub(r'\[[A-Z_-]+:\s*[^\]]+\]', '', script_text)
    words = cleaned.split()
    return len(words)


def _build_world_summary(world_bible):
    """Build a concise world bible summary for prompt injection."""
    lines = []

    nation = world_bible.get("nation", {})
    lines.append(f"Country: {nation.get('name', 'United States')}")
    lines.append(f"President: {nation.get('president', 'Unknown')}")
    lines.append(f"Vice President: {nation.get('vice_president', 'Unknown')}")
    if "government_note" in nation:
        lines.append(f"Government note: {nation['government_note']}")

    # World rules (real/fictional mixing guidance)
    world_rules = world_bible.get("world_rules", {})
    if world_rules:
        lines.append("\nREAL ENTITIES YOU MAY REFERENCE:")
        for item in world_rules.get("real_entities_allowed", []):
            lines.append(f"  - {item}")
        lines.append("\nMUST BE FICTIONAL:")
        for item in world_rules.get("must_be_fictional", []):
            lines.append(f"  - {item}")
        if "mixing_rule" in world_rules:
            lines.append(f"\nMIXING RULE: {world_rules['mixing_rule']}")

    lines.append("\nOngoing stories:")
    for story in world_bible.get("ongoing_stories", []):
        location_note = ""
        if "location_type" in story:
            location_note = f" [{story['location_type']} location: {story.get('location', '')}]"
        lines.append(f"  - {story['headline']} ({story['status']}){location_note}: {story['summary']}")

    lines.append("\nAvailable places (mix of real and fictional):")
    for place in world_bible.get("places", world_bible.get("fictional_places", [])):
        if isinstance(place, dict):
            real_tag = "REAL" if place.get("real", False) else "FICTIONAL"
            lines.append(f"  - {place['name']}, {place['state']} [{real_tag}]")
        else:
            lines.append(f"  - {place}")

    lines.append("\nFictional organizations:")
    for org in world_bible.get("fictional_organizations", []):
        lines.append(f"  - {org}")

    return "\n".join(lines)


def _extract_tags(script, tag_name):
    """Extract [TAG: content] values from script text."""
    pattern = rf'\[{tag_name}:\s*(.+?)\]'
    return re.findall(pattern, script, re.IGNORECASE)


def _classify_topic(script_text, topic_weights):
    """Simple keyword-based topic classification of the generated script."""
    text = script_text.lower()
    scores = {}

    keyword_map = {
        "politics": ["senator", "governor", "president", "legislation", "vote", "bill", "committee", "caucus"],
        "infrastructure": ["bridge", "road", "port", "rail", "construction", "pipeline", "transit", "grid"],
        "science": ["study", "research", "university", "climate", "species", "lab", "data", "findings"],
        "crime": ["arrest", "police", "investigation", "suspect", "charges", "detective", "victim"],
        "international": ["embassy", "foreign", "treaty", "summit", "allies", "trade", "sanctions"],
    }

    for topic, keywords in keyword_map.items():
        scores[topic] = sum(1 for kw in keywords if kw in text)

    if max(scores.values()) == 0:
        return "general"
    return max(scores, key=scores.get)
