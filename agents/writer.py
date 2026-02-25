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


def _select_blueprints(blueprints, topics_covered=None):
    """
    Select 2-3 blueprints for the writer, avoiding topics already covered.
    Prioritizes blueprints with rich specifics (numbers, geographic detail).
    """
    if not blueprints:
        return []

    covered = set(topics_covered or [])

    # Score each blueprint
    scored = []
    for bp in blueprints:
        score = 0
        topic = bp.get("topic", "")

        # Penalize already-covered topics
        if topic in covered:
            score -= 5

        # Reward rich specifics
        specifics = bp.get("specifics", {})
        score += len(specifics.get("numbers", [])) * 2
        score += 2 if specifics.get("geographic_detail") else 0
        score += len(specifics.get("institutional_actors", []))
        score += 1 if specifics.get("stakes_level") in ("high", "critical") else 0

        # Reward having a good summary
        if bp.get("summary_frame") and len(bp["summary_frame"]) > 30:
            score += 3

        scored.append((score, bp))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Pick top 3, ensuring topic diversity
    selected = []
    selected_topics = set()
    for score, bp in scored:
        topic = bp.get("topic", "")
        if topic not in selected_topics or len(selected) < 2:
            selected.append(bp)
            selected_topics.add(topic)
        if len(selected) >= 3:
            break

    return selected


def generate_script(config, world_bible, news_context, topics_covered=None):
    """
    Generate a single anchor script using Claude.
    Retries if word count is outside 60-75 range.

    Args:
        config: channel config
        world_bible: world bible dict
        news_context: scraped news context
        topics_covered: list of topic strings already generated this batch (for diversity)

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

    # Pick a random anchor (skip paused ones)
    active_anchors = [a for a in world_bible["anchors"] if not a.get("paused", False)]
    anchor = random.choice(active_anchors if active_anchors else world_bible["anchors"])

    # Build world bible summary for context injection
    world_summary = _build_world_summary(world_bible)

    # Get operator dial settings
    dials = config.get("dials", {})
    tone = dials.get("tone", "concerned")
    topic_weights = dials.get("topic_weights", {})

    system_msg = """You are a television news script writer. You write extremely concise broadcast copy. Every word must earn its place. You never exceed the word count you are given. You write in plain text only — no markdown, no formatting, no character names as prefixes."""

    # Build blueprint block from rich scraped data
    blueprints = news_context.get("story_blueprints", [])
    conflict_types = news_context.get("conflict_types", [])
    blueprint_block = ""
    if blueprints:
        selected = _select_blueprints(blueprints, topics_covered)
        if selected:
            blueprint_block = "\n\nREAL NEWS BLUEPRINTS — Pick ONE and write a story that CLOSELY mirrors its structure:\n"
            for i, bp in enumerate(selected[:3]):
                blueprint_block += f"\nBLUEPRINT {i+1}:\n"
                blueprint_block += f"  Headline pattern: {bp['headline_frame']}\n"
                if bp.get("summary_frame"):
                    blueprint_block += f"  Story skeleton: {bp['summary_frame'][:200]}\n"
                nums = bp.get("specifics", {}).get("numbers", [])
                if nums:
                    blueprint_block += f"  Key numbers: {', '.join(nums[:3])}\n"
                actors = bp.get("specifics", {}).get("institutional_actors", [])
                if actors:
                    blueprint_block += f"  Actors involved: {', '.join(actors[:3])}\n"
                blueprint_block += f"  Framing: {bp.get('framing_style', 'development')}\n"
                blueprint_block += f"  Conflict type: {bp.get('conflict_type', 'development')}\n"
    # Fallback to flat story shapes if no blueprints
    elif news_context.get("story_shapes"):
        shapes = news_context["story_shapes"]
        blueprint_block = "\n\nREAL-WORLD NEWS SHAPES (use ONE as close inspiration):\n"
        for shape in shapes[:4]:
            blueprint_block += f"  - {shape}\n"
    if conflict_types:
        blueprint_block += f"\nACTIVE CONFLICT TYPES in today's news: {', '.join(conflict_types)}"

    # Pull accumulated style knowledge if available
    style_context = ""
    try:
        from agents.style_memory import load_style_library, get_style_context_for_writer
        style_lib = load_style_library()
        style_context = get_style_context_for_writer(style_lib)
        if style_context:
            style_context = f"\n\n{style_context}"
    except Exception:
        pass

    # Build diversity block if we've already covered topics
    diversity_block = ""
    if topics_covered:
        covered_str = ", ".join(topics_covered)
        diversity_block = f"""

DIVERSITY REQUIREMENT — CRITICAL:
This batch has already covered these topics/subjects: {covered_str}
You MUST choose a COMPLETELY DIFFERENT topic, location, and angle. Do NOT repeat or revisit any of the above subjects.
Pick from underrepresented categories: politics, international, science, crime, health, education, technology, business, weather, military, or sports."""

    prompt = f"""Write a single anchor read for This News Now (TNN).

WORLD CONTEXT:
{world_summary}

NEWS REGISTER: {news_context.get('register', 'tense')}
TRENDING: {', '.join(news_context.get('trending_topics', ['politics', 'economy']))}
TONE: {tone}
TOPIC WEIGHTS: {json.dumps(topic_weights)}
{blueprint_block}{style_context}{diversity_block}

BLUEPRINT USAGE — CRITICAL:
Pick ONE blueprint above and write a story that CLOSELY mirrors its structure, framing, and specificity level. Keep similar numbers, similar institutional actors, and the same geographic scope — but change ALL names of people, companies, and specific organizations to FICTIONAL ones. The story should read like a parallel-universe version of the real headline. Someone who read the real news today should think "that sounds vaguely familiar but different."

HARD REQUIREMENTS:
- EXACTLY 60 to 75 spoken words. Not 76. Not 100. Count carefully.
- Tags like [CHYRON: ...] and [B-ROLL: ...] do NOT count toward the word limit.
- Cover ONE story. One angle. No pivoting to a second story.
- End with a natural anchor sign-off: a toss to break, a tease of what's ahead, or a simple "more on this as it develops" style line. Keep it under 10 words.

ANCHOR: {anchor['name']} ({anchor['gender']})

CONTENT RULES:
- Deadpan. No humor, no irony.
- You MAY use real US places, real federal agencies (EPA, FBI, FEMA, etc.), real political parties.
- Use places and storylines from the world context, or invent entirely new ones.
- One [CHYRON: text] tag and one [B-ROLL: description] tag, placed inline where they'd appear on screen.
- No markdown. No bold. No anchor name prefix. Just the spoken script with inline tags.

*** NO REAL NAMES — THIS IS ABSOLUTELY CRITICAL ***
Every single person named in your script MUST be fictional. Every company MUST be fictional.
- NO real politicians: not Marco Rubio, not Mitch McConnell, not Chuck Schumer, not Nancy Pelosi, not any real senator, cabinet member, or governor. INVENT a name.
- NO real sitting officials: instead of "Secretary of State Marco Rubio" → use "Secretary of State [fictional name]" like "Secretary of State Diane Mercer".
- For the President or VP, do NOT name them — just say "the President", "the White House", "the administration".
- NO real companies: not Boeing, not Amazon, not Google, not Tesla, not Meta, not Apple, not ExxonMobil, not any real corporation. INVENT a company name.
  Instead of "Boeing 737" → "Meridian Aerospace 700". Instead of "Amazon warehouse" → "Crestline Logistics facility".
- NO real celebrities, CEOs, journalists, or public figures of any kind.
- If you're unsure whether a name is real, INVENT a new one. It is always safer to invent.
- The ONLY real-world proper nouns allowed are: place names (cities, states, countries), government agency names (FBI, EPA), political party names (Democrat, Republican), and institutional roles (President, Senator, Governor).

STORY TYPE VARIETY — IMPORTANT:
Not every story is an investigation or a federal probe. Real news desks cover a wide range. Choose ONE of these story types at random:
- HARD NEWS: breaking events, accidents, natural disasters, political votes, court rulings
- ECONOMICS: market moves, layoffs, company earnings, housing data, trade disputes, inflation reports
- TECHNOLOGY: product launches, data breaches, AI developments, social media policy, startup failures
- INTERNATIONAL: diplomatic tensions, foreign elections, refugee situations, trade deals, military postures
- HEALTH/SCIENCE: disease outbreaks, drug approvals, research findings, hospital closures, clinical trials
- EDUCATION: school board fights, university scandals, testing policy changes, teacher strikes
- WEATHER/ENVIRONMENT: severe storms, drought, flooding, wildfire, seasonal anomalies
- FLUFF/HUMAN INTEREST: local record-breakers, animal rescues, community events, quirky milestones, charity drives
- SPORTS: team relocations, player suspensions, stadium deals, league disputes, doping scandals
Do NOT write another "federal agency probes/raids/investigates" story unless that's truly the best fit. Vary the verbs too — not everything is a probe.

CAPITALIZATION — MANDATORY:
- ALL acronyms must be fully capitalized: EPA, FBI, FEMA, DHS, FAA, NLRB, ACLU, NATO, FDA, CDC, DOD, DOE, HUD, SEC, etc.
- ALL country names must be properly capitalized: United States, South Korea, North Korea, China, Russia, Ukraine, Israel, Iran, etc.
- ALL proper nouns (city names, state names, agency names, organization names) must be correctly capitalized.
- This is broadcast copy — proper capitalization is non-negotiable.

EXAMPLE of correct length and format (68 words — note ALL names are fictional):
Good evening. A federal grand jury in Atlanta has returned a twelve-count indictment against three former executives of Rayburn Holdings, alleging wire fraud and securities manipulation totaling more than two hundred million dollars. Lead prosecutor Anna Whitmore confirmed the charges this afternoon, calling it one of the largest corporate fraud cases in the Southeast. [CHYRON: ATLANTA GRAND JURY INDICTS RAYBURN EXECS] [B-ROLL: Federal courthouse exterior, attorneys exiting building] Bail hearings are set for Friday. We'll continue to follow this.
Notice: "Rayburn Holdings" is a FICTIONAL company. "Anna Whitmore" is a FICTIONAL person. This is required.

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

    # Fix capitalization of acronyms and proper nouns
    script_text = _fix_capitalization(script_text)

    # Scrub any real names that slipped through
    script_text = _scrub_real_names(script_text)

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

    # Track which blueprint inspired this story
    inspiration = None
    if blueprints:
        selected = _select_blueprints(blueprints, topics_covered)
        if selected:
            inspiration = selected[0].get("headline_frame")

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
        "inspiration_blueprint": inspiration,
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
    lines.append("President: Refer to as 'the President' — do NOT use any real name.")
    lines.append("Vice President: Refer to as 'the Vice President' — do NOT use any real name.")
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
        "politics": ["senator", "governor", "president", "legislation", "vote", "bill", "committee", "caucus", "partisan", "bipartisan", "democrat", "republican"],
        "economics": ["market", "stocks", "inflation", "earnings", "layoffs", "recession", "gdp", "trade deficit", "interest rate", "federal reserve", "wall street", "dow", "nasdaq", "unemployment"],
        "technology": ["software", "app", "data breach", "hack", "ai ", "artificial intelligence", "startup", "tech", "social media", "algorithm", "silicon valley", "cyber"],
        "infrastructure": ["bridge", "road", "port", "rail", "construction", "pipeline", "transit", "grid", "highway"],
        "science": ["study", "research", "university", "species", "lab", "findings", "researchers", "experiment", "peer-reviewed"],
        "health": ["hospital", "vaccine", "disease", "outbreak", "clinical", "patients", "fda", "cdc", "drug", "pharmaceutical", "medical", "surgeon"],
        "crime": ["arrest", "police", "suspect", "charges", "detective", "victim", "murder", "robbery", "shooting", "indictment", "convicted"],
        "international": ["embassy", "foreign", "treaty", "summit", "allies", "sanctions", "diplomat", "nato", "united nations", "overseas"],
        "education": ["school", "teacher", "student", "campus", "tuition", "curriculum", "superintendent", "school board", "graduation"],
        "weather": ["storm", "hurricane", "tornado", "flood", "drought", "wildfire", "blizzard", "evacuation", "temperature", "forecast"],
        "fluff": ["community", "volunteer", "charity", "rescued", "record-breaking", "celebrates", "festival", "tradition", "heartwarming", "milestone"],
        "sports": ["team", "stadium", "league", "coach", "playoff", "championship", "athlete", "draft", "season"],
    }

    for topic, keywords in keyword_map.items():
        scores[topic] = sum(1 for kw in keywords if kw in text)

    if max(scores.values()) == 0:
        return "general"
    return max(scores, key=scores.get)


def _fix_capitalization(script_text):
    """Fix common capitalization issues in generated scripts."""
    # Acronyms that must be fully capitalized
    acronyms = [
        "EPA", "FBI", "FEMA", "DHS", "FAA", "NLRB", "ACLU", "NATO", "FDA",
        "CDC", "DOD", "DOE", "HUD", "SEC", "CIA", "NSA", "TSA", "ICE",
        "OSHA", "IRS", "DOJ", "ATF", "DEA", "NTSB", "USDA", "FCC", "FTC",
        "NIH", "NOAA", "NASA", "FISA", "NAFTA", "USMCA", "GDP", "GNP",
        "CEO", "CFO", "COO", "CTO",
        # Additional common acronyms
        "HHS", "SCOTUS", "POTUS", "DOT", "USPS", "ICJ", "IMF",
        "NYPD", "LAPD", "IPO", "NYSE", "NASDAQ", "USCIS", "CBP",
        "SBA", "GSA", "OPM", "GAO", "CBO", "OMB", "NRC",
    ]

    # Risky acronyms: only fix if already partially capitalized
    # (avoids turning common words like "who" or "un" into acronyms)
    risky_acronyms = ["VA", "WHO", "UN", "EU", "AI"]

    # Country / proper noun pairs: (lowercase pattern, correct form)
    proper_nouns = [
        # Countries
        ("united states", "United States"),
        ("south korea", "South Korea"),
        ("north korea", "North Korea"),
        ("united kingdom", "United Kingdom"),
        ("saudi arabia", "Saudi Arabia"),
        ("new zealand", "New Zealand"),
        ("south africa", "South Africa"),
        ("puerto rico", "Puerto Rico"),
        ("costa rica", "Costa Rica"),
        ("el salvador", "El Salvador"),
        ("sri lanka", "Sri Lanka"),
        ("hong kong", "Hong Kong"),
        # US cities / states
        ("new york", "New York"),
        ("los angeles", "Los Angeles"),
        ("san francisco", "San Francisco"),
        ("washington d.c.", "Washington D.C."),
        ("new hampshire", "New Hampshire"),
        ("new jersey", "New Jersey"),
        ("new mexico", "New Mexico"),
        ("rhode island", "Rhode Island"),
        ("west virginia", "West Virginia"),
        ("south carolina", "South Carolina"),
        ("north carolina", "North Carolina"),
        ("south dakota", "South Dakota"),
        ("north dakota", "North Dakota"),
        # Additional US cities
        ("san antonio", "San Antonio"),
        ("san diego", "San Diego"),
        ("las vegas", "Las Vegas"),
        ("des moines", "Des Moines"),
        ("el paso", "El Paso"),
        ("baton rouge", "Baton Rouge"),
        ("st. louis", "St. Louis"),
        ("salt lake city", "Salt Lake City"),
        ("fort worth", "Fort Worth"),
        ("little rock", "Little Rock"),
        ("grand rapids", "Grand Rapids"),
        ("corpus christi", "Corpus Christi"),
        # Federal departments (full names)
        ("department of energy", "Department of Energy"),
        ("department of education", "Department of Education"),
        ("department of justice", "Department of Justice"),
        ("department of defense", "Department of Defense"),
        ("department of homeland security", "Department of Homeland Security"),
        ("department of transportation", "Department of Transportation"),
        ("department of state", "Department of State"),
        ("department of labor", "Department of Labor"),
        ("department of agriculture", "Department of Agriculture"),
        ("department of commerce", "Department of Commerce"),
        ("department of health and human services", "Department of Health and Human Services"),
        ("department of housing and urban development", "Department of Housing and Urban Development"),
        ("department of the interior", "Department of the Interior"),
        ("department of the treasury", "Department of the Treasury"),
        ("department of veterans affairs", "Department of Veterans Affairs"),
        # Federal agencies (full names)
        ("environmental protection agency", "Environmental Protection Agency"),
        ("federal aviation administration", "Federal Aviation Administration"),
        ("federal trade commission", "Federal Trade Commission"),
        ("federal bureau of investigation", "Federal Bureau of Investigation"),
        ("federal communications commission", "Federal Communications Commission"),
        ("federal emergency management agency", "Federal Emergency Management Agency"),
        ("national weather service", "National Weather Service"),
        ("national security agency", "National Security Agency"),
        ("securities and exchange commission", "Securities and Exchange Commission"),
        ("food and drug administration", "Food and Drug Administration"),
        ("centers for disease control", "Centers for Disease Control"),
        ("national labor relations board", "National Labor Relations Board"),
        ("national transportation safety board", "National Transportation Safety Board"),
        ("internal revenue service", "Internal Revenue Service"),
        ("bureau of alcohol, tobacco, firearms", "Bureau of Alcohol, Tobacco, Firearms"),
        ("drug enforcement administration", "Drug Enforcement Administration"),
        ("occupational safety and health administration", "Occupational Safety and Health Administration"),
    ]

    # Fix acronyms using word-boundary matching (case-insensitive)
    # Also handles possessive forms like DOJ's, EPA's
    for acr in acronyms:
        pattern = re.compile(r'\b' + acr + r"(?='s\b|\b)", re.IGNORECASE)
        script_text = pattern.sub(acr, script_text)

    # Risky acronyms: only uppercase if first letter is already capitalized
    # (e.g., "Va" → "VA" but not "various" → "VArious")
    for acr in risky_acronyms:
        # Match the mixed-case form (first letter upper, rest lower)
        mixed = acr[0].upper() + acr[1:].lower()
        pattern = re.compile(r'\b' + re.escape(mixed) + r"(?='s\b|\b)")
        script_text = pattern.sub(acr, script_text)

    # Fix proper nouns (case-insensitive replacement)
    for lower_form, correct_form in proper_nouns:
        pattern = re.compile(re.escape(lower_form), re.IGNORECASE)
        script_text = pattern.sub(correct_form, script_text)

    return script_text


# ---- Real-name scrubber (safety net) ----

# Mapping of real names → fictional replacements for common offenders
_REAL_PEOPLE_MAP = {
    # Current / recent US politicians (case-insensitive matching)
    "Marco Rubio": "Diane Mercer",
    "Mitch McConnell": "Richard Haldane",
    "Chuck Schumer": "Leonard Pratt",
    "Nancy Pelosi": "Margaret Ashworth",
    "Kevin McCarthy": "Gerald Taft",
    "Mike Johnson": "Douglas Crane",
    "Hakeem Jeffries": "Warren Ellison",
    "Pete Buttigieg": "Thomas Hadley",
    "Merrick Garland": "Lawrence Beckett",
    "Lloyd Austin": "Kenneth Aldridge",
    "Janet Yellen": "Catherine Ainsley",
    "Antony Blinken": "Philip Navarro",
    "Gina Raimondo": "Valerie Chalmers",
    "Miguel Cardona": "Robert Estrada",
    "Alejandro Mayorkas": "Vincent Dorado",
    "Deb Haaland": "Sandra Whitfield",
    "Tom Vilsack": "Harold Brennan",
    "Denis McDonough": "Patrick Calloway",
    "Xavier Becerra": "Daniel Montoya",
    "Michael Regan": "James Cortland",
    "Jen Psaki": "Karen Lindsey",
    "Karine Jean-Pierre": "Michelle Gaston",
    "Ron DeSantis": "David Caldwell",
    "Gavin Newsom": "Andrew Sheffield",
    "Greg Abbott": "William Landers",
    "Donald Trump": "the President",
    "JD Vance": "the Vice President",
    "Joe Biden": "the former President",
    "Kamala Harris": "the former Vice President",
    "Elon Musk": "Roland Voss",
    "Mark Zuckerberg": "Nathan Brower",
    "Jeff Bezos": "Clarke Whitmore",
    "Tim Cook": "Edward Langford",
    "Sundar Pichai": "Rajiv Anand",
    "Satya Nadella": "Arjun Patel",
    "Sam Altman": "Derek Calloway",
    "Jamie Dimon": "Frederick Nash",
}

_REAL_COMPANIES_MAP = {
    # Big tech & Fortune 100 (match whole word)
    "Boeing": "Meridian Aerospace",
    "Amazon": "Crestline Logistics",
    "Google": "Nexagen Technologies",
    "Alphabet": "Nexagen Holdings",
    "Facebook": "ConnectSphere",
    "Meta Platforms": "ConnectSphere Inc",
    "Apple Inc": "Orion Electronics",
    "Microsoft": "Vertex Software",
    "Tesla": "Volta Motors",
    "SpaceX": "Aether Launch Systems",
    "Netflix": "StreamVault",
    "Walmart": "Redfield Retail",
    "ExxonMobil": "Crestfield Energy",
    "Chevron": "Harland Petroleum",
    "JPMorgan": "Stanton Financial",
    "Goldman Sachs": "Whitmore Capital",
    "Lockheed Martin": "Hargrove Defense",
    "Raytheon": "Aldridge Systems",
    "Northrop Grumman": "Vanguard Aerospace",
    "General Motors": "Continental Motors",
    "Ford Motor": "Hartfield Automotive",
    "Pfizer": "Thorngate Pharmaceuticals",
    "Johnson & Johnson": "Mercer Health Group",
    "UnitedHealth": "Crossfield Health",
    "Citigroup": "Belmont Banking",
    "Bank of America": "National Meridian Bank",
    "Wells Fargo": "Pacific Standard Bank",
    "Shell": "Gulfmark Energy",
    "BP": "Harland Petroleum",
    "Uber": "Stridelink",
    "Lyft": "GoWave",
    "OpenAI": "Frontier Labs",
    "Twitter": "BroadCast Social",
    "TikTok": "ClipStream",
    "Disney": "Crescent Entertainment",
    "Comcast": "Meridian Media",
    "AT&T": "Norland Communications",
    "Verizon": "Clearpoint Wireless",
}


def _scrub_real_names(script_text):
    """
    Safety-net post-processor: replace any real politician or company names
    that slipped through the prompt instructions with fictional alternatives.
    """
    # Scrub real people
    for real_name, fictional_name in _REAL_PEOPLE_MAP.items():
        pattern = re.compile(re.escape(real_name), re.IGNORECASE)
        if pattern.search(script_text):
            script_text = pattern.sub(fictional_name, script_text)
            print(f"  ⚠ Scrubbed real name: '{real_name}' → '{fictional_name}'")

    # Scrub real companies (word-boundary match to avoid partial hits)
    for real_co, fictional_co in _REAL_COMPANIES_MAP.items():
        pattern = re.compile(r'\b' + re.escape(real_co) + r'\b', re.IGNORECASE)
        if pattern.search(script_text):
            script_text = pattern.sub(fictional_co, script_text)
            print(f"  ⚠ Scrubbed real company: '{real_co}' → '{fictional_co}'")

    return script_text
