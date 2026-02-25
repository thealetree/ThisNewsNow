"""
Scraper Agent — Pulls real news headlines and extracts rich "story blueprints"
to inform fictional story generation.

Grabs headlines + summaries from major RSS feeds, then builds detailed
anonymized blueprints that preserve the structure, framing, specifics (numbers,
geographic detail, institutional actors) of real stories — while stripping
all proper names of people and companies. The writer uses these blueprints
to craft parallel-universe stories that feel reality-adjacent.
"""

import feedparser
import re
import requests
from datetime import datetime


# Major RSS feeds for broad, current coverage
RSS_FEEDS = [
    ("Google News", "https://news.google.com/rss"),
    ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines"),
    ("CBS News", "https://www.cbsnews.com/latest/rss/main"),
    ("ABC News", "https://abcnews.go.com/abcnews/topstories"),
    ("NY Times", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
]


# ── Topic keyword maps ──
TOPIC_KEYWORDS = {
    "politics": [
        "president", "senate", "congress", "vote", "election", "bill",
        "governor", "legislation", "party", "democrat", "republican",
        "speaker", "caucus", "impeach", "campaign", "bipartisan",
        "executive order", "veto", "confirmation", "committee",
    ],
    "infrastructure": [
        "bridge", "road", "rail", "transit", "port", "construction",
        "highway", "pipeline", "grid", "broadband", "dam", "airport",
        "levee", "infrastructure", "utility", "power grid",
    ],
    "science": [
        "study", "research", "nasa", "climate", "species", "medical",
        "vaccine", "ai", "technology", "university", "findings",
        "discovery", "lab", "experiment", "satellite", "data",
    ],
    "crime": [
        "arrest", "shooting", "murder", "police", "fbi", "fraud",
        "trial", "sentenced", "charges", "indictment", "homicide",
        "robbery", "theft", "suspect", "investigation", "cartel",
    ],
    "international": [
        "ukraine", "china", "eu", "nato", "united nations", "foreign",
        "trade", "tariff", "summit", "sanctions", "embassy", "allies",
        "treaty", "diplomacy", "missile", "conflict", "border",
    ],
    "economy": [
        "market", "stock", "inflation", "jobs", "unemployment", "fed",
        "interest rate", "gdp", "recession", "housing", "retail",
        "banking", "debt", "deficit", "earnings", "layoffs", "wages",
    ],
    "weather": [
        "storm", "hurricane", "tornado", "flood", "wildfire", "drought",
        "snow", "heat wave", "evacuation", "fema", "disaster",
        "earthquake", "tsunami", "blizzard",
    ],
    "health": [
        "hospital", "cdc", "outbreak", "virus", "patients", "drug",
        "fda", "overdose", "mental health", "opioid", "treatment",
    ],
    "environment": [
        "epa", "pollution", "contamination", "water quality", "toxic",
        "chemical", "spill", "emissions", "carbon", "cleanup",
        "endangered", "conservation",
    ],
}

# Conflict type patterns (what kind of story is this?)
CONFLICT_PATTERNS = {
    "standoff": ["deadlock", "stalled", "impasse", "standoff", "refuses", "blocked", "gridlock", "dispute"],
    "crisis": ["crisis", "emergency", "disaster", "catastrophe", "collapse", "shortage", "outbreak"],
    "investigation": ["probe", "investigation", "inquiry", "audit", "review", "inspector", "whistleblower"],
    "protest": ["protest", "rally", "march", "demonstration", "strike", "walkout", "picket"],
    "development": ["announces", "unveils", "launches", "proposes", "expands", "opens", "approves"],
    "tragedy": ["killed", "dead", "death toll", "victims", "shooting", "crash", "explosion"],
    "legal": ["court", "judge", "ruling", "lawsuit", "verdict", "appeal", "settlement", "convicted"],
}

# Framing style patterns — how is the headline structured?
FRAMING_PATTERNS = {
    "announcement": ["announces", "unveils", "launches", "introduces", "rolls out", "releases", "signs"],
    "accusation": ["charges", "alleges", "accuses", "indicts", "blames", "sues", "files against"],
    "revelation": ["reveals", "discovers", "uncovers", "exposes", "finds", "leaked", "obtained"],
    "escalation": ["escalates", "worsens", "intensifies", "spreads", "grows", "surges", "spikes"],
    "resolution": ["settles", "resolves", "agrees", "ends", "reaches deal", "signs agreement"],
    "warning": ["warns", "threatens", "could", "risk", "fears", "braces for", "prepares"],
    "reaction": ["responds", "reacts", "pushes back", "denounces", "praises", "defends", "criticizes"],
    "development": ["reports", "says", "plans", "considers", "moves to", "seeks", "looks at"],
}

# ── Known names for anonymization (imported from writer at runtime) ──
_PEOPLE_ROLES = None
_COMPANY_SECTORS = None


def _load_name_maps():
    """Lazily load name maps from writer module for anonymization."""
    global _PEOPLE_ROLES, _COMPANY_SECTORS
    if _PEOPLE_ROLES is not None:
        return

    try:
        from agents.writer import _REAL_PEOPLE_MAP, _REAL_COMPANIES_MAP
    except ImportError:
        _PEOPLE_ROLES = {}
        _COMPANY_SECTORS = {}
        return

    # Map real people to role descriptions
    _PEOPLE_ROLES = {}
    for name in _REAL_PEOPLE_MAP:
        lower = name.lower()
        if "president" in _REAL_PEOPLE_MAP[name].lower():
            _PEOPLE_ROLES[name] = _REAL_PEOPLE_MAP[name]
        elif any(w in lower for w in ["rubio", "mcconnell", "schumer", "pelosi",
                                       "mccarthy", "johnson", "jeffries"]):
            _PEOPLE_ROLES[name] = "a senior lawmaker"
        elif any(w in lower for w in ["desantis", "newsom", "abbott"]):
            _PEOPLE_ROLES[name] = "a state governor"
        elif any(w in lower for w in ["musk", "zuckerberg", "bezos", "cook",
                                       "pichai", "nadella", "altman", "dimon"]):
            _PEOPLE_ROLES[name] = "a prominent tech executive"
        else:
            _PEOPLE_ROLES[name] = "a senior official"

    # Map real companies to sector descriptions
    _COMPANY_SECTORS = {
        "Boeing": "a major aerospace manufacturer",
        "Amazon": "a major online retail corporation",
        "Google": "a major technology company",
        "Alphabet": "a major technology conglomerate",
        "Facebook": "a major social media company",
        "Meta Platforms": "a major social media conglomerate",
        "Apple Inc": "a major electronics company",
        "Microsoft": "a major software corporation",
        "Tesla": "a major electric vehicle maker",
        "SpaceX": "a private space launch company",
        "Netflix": "a major streaming service",
        "Walmart": "a major retail chain",
        "ExxonMobil": "a major oil corporation",
        "Chevron": "a major energy company",
        "JPMorgan": "a major investment bank",
        "Goldman Sachs": "a major investment bank",
        "Lockheed Martin": "a major defense contractor",
        "Raytheon": "a major defense contractor",
        "Northrop Grumman": "a major aerospace firm",
        "General Motors": "a major automaker",
        "Ford Motor": "a major automaker",
        "Pfizer": "a major pharmaceutical company",
        "Johnson & Johnson": "a major healthcare corporation",
        "UnitedHealth": "a major health insurer",
        "OpenAI": "a major AI company",
        "TikTok": "a major social media platform",
        "Disney": "a major entertainment company",
    }

    # Add remaining companies with generic label
    for co in _REAL_COMPANIES_MAP:
        if co not in _COMPANY_SECTORS:
            _COMPANY_SECTORS[co] = "a major corporation"


def scrape_news_context():
    """
    Pull headlines + summaries from RSS feeds and extract:
    - Trending topics (weighted)
    - Emotional register (calm/tense/chaotic)
    - Story blueprints: rich anonymized story structures
    - Conflict types currently active in the news

    Returns a dict consumed by the writer agent.
    """
    stories_raw = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=10, headers={
                "User-Agent": "ThisNewsNow/1.0 (RSS Reader)"
            })
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:18]:
                title = entry.get("title", "").strip()
                summary = ""
                if entry.get("summary"):
                    summary = _clean_html(entry["summary"])[:400]
                elif entry.get("description"):
                    summary = _clean_html(entry["description"])[:400]

                if title:
                    stories_raw.append({
                        "source": source_name,
                        "title": title,
                        "summary": summary,
                    })
        except Exception as e:
            print(f"  Warning: Could not fetch {source_name}: {e}")

    headlines = [s["title"] for s in stories_raw]
    all_text = " ".join(headlines + [s["summary"] for s in stories_raw]).lower()

    # ── Classify topics ──
    topic_counts = {t: 0 for t in TOPIC_KEYWORDS}
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            topic_counts[topic] += all_text.count(kw)

    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    trending = [t[0] for t in sorted_topics[:4] if t[1] > 0]
    if not trending:
        trending = ["politics", "economy", "infrastructure"]

    # ── Detect active conflict types ──
    active_conflicts = []
    for ctype, keywords in CONFLICT_PATTERNS.items():
        score = sum(all_text.count(kw) for kw in keywords)
        if score > 0:
            active_conflicts.append((ctype, score))
    active_conflicts.sort(key=lambda x: x[1], reverse=True)
    conflict_types = [c[0] for c in active_conflicts[:3]]
    if not conflict_types:
        conflict_types = ["development", "investigation"]

    # ── Register heuristic ──
    urgent_words = ["breaking", "emergency", "crisis", "killed", "shooting",
                     "attack", "war", "collapse", "explosion", "evacuate"]
    calm_words = ["announces", "plans", "report", "study", "expected",
                   "scheduled", "opens", "celebrates", "approves"]
    urgent_count = sum(1 for w in urgent_words if w in all_text)
    calm_count = sum(1 for w in calm_words if w in all_text)

    if urgent_count > 5:
        register = "chaotic"
    elif urgent_count > 2:
        register = "tense"
    elif calm_count > urgent_count:
        register = "calm"
    else:
        register = "tense"

    # ── Build story blueprints ──
    blueprints = _extract_story_blueprints(stories_raw[:40])

    # Backward-compat: also provide flat story_shapes
    story_shapes = [bp["headline_frame"] for bp in blueprints]

    # ── Dominant formats ──
    formats = ["anchor_read"]
    if urgent_count > 2:
        formats.append("breaking")
    if any("investigation" in s["title"].lower() or "probe" in s["title"].lower()
           for s in stories_raw):
        formats.append("investigation_report")
    if any("strike" in s["title"].lower() or "protest" in s["title"].lower()
           for s in stories_raw):
        formats.append("field_report")

    context = {
        "trending_topics": trending,
        "register": register,
        "dominant_formats": formats,
        "conflict_types": conflict_types,
        "story_blueprints": blueprints,
        "story_shapes": story_shapes,
        "headline_count": len(headlines),
        "topic_counts": topic_counts,
        "timestamp": datetime.now().isoformat(),
    }

    print(f"  Scraped {len(headlines)} headlines. Register: {register}. "
          f"Topics: {trending}. Conflicts: {conflict_types}")
    print(f"  Story blueprints: {len(blueprints)} extracted")

    # ── Update style library if available ──
    try:
        from agents.style_memory import load_style_library, update_from_scrape, save_style_library
        library = load_style_library()
        library = update_from_scrape(library, blueprints, register, topic_counts)
        save_style_library(library)
        print(f"  Style library updated: {library.get('total_scrapes', 0)} total scrapes, "
              f"{len(library.get('headline_templates', []))} templates")
    except Exception as e:
        print(f"  Warning: Could not update style library: {e}")

    return context


# ─────────────────────────────────────────────────────
# Blueprint extraction
# ─────────────────────────────────────────────────────

def _extract_story_blueprints(stories, max_blueprints=8):
    """
    Extract detailed 'story blueprints' from real headlines and summaries.

    A blueprint preserves the structure, framing, and specifics of a real story
    while stripping proper names of people and companies. Each blueprint has:
    - headline_frame: anonymized headline
    - summary_frame: anonymized summary
    - topic, conflict_type, framing_style
    - specifics: numbers, geographic detail, stakes, actors
    """
    _load_name_maps()
    blueprints = []
    seen_keys = set()

    for story in stories:
        title = story["title"]
        summary = story.get("summary", "")
        source = story.get("source", "")
        combined = f"{title} {summary}".lower()

        # Classify topic (score-based, not first-match)
        topic = _classify_topic(combined)
        if not topic:
            continue

        # Classify conflict type
        conflict = _classify_conflict(combined)

        # Avoid duplicates of same topic+conflict
        key = f"{topic}_{conflict}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # Build the blueprint
        headline_frame = _anonymize_text(title)
        summary_frame = _anonymize_text(summary) if summary else ""
        framing = _detect_framing_style(title, summary)
        specifics = _extract_specifics(title, summary)

        # Skip if anonymization produced something too short/empty
        if len(headline_frame) < 15:
            continue

        blueprints.append({
            "headline_frame": headline_frame,
            "summary_frame": summary_frame,
            "topic": topic,
            "conflict_type": conflict,
            "specifics": specifics,
            "framing_style": framing,
            "source": source,
        })

        if len(blueprints) >= max_blueprints:
            break

    return blueprints


def _classify_topic(text_lower):
    """Score-based topic classification. Returns best topic or None."""
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[topic] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def _classify_conflict(text_lower):
    """Score-based conflict type classification."""
    scores = {}
    for ctype, keywords in CONFLICT_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[ctype] = score
    if not scores:
        return "development"
    return max(scores, key=scores.get)


def _anonymize_text(text):
    """
    Strip real names of people and companies while preserving structure,
    numbers, geographic hints, agency names, and institutional roles.
    """
    if not text:
        return ""

    result = text

    # 1. Replace known real people with role descriptions
    if _PEOPLE_ROLES:
        for name, role in sorted(_PEOPLE_ROLES.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            result = pattern.sub(role, result)

    # 2. Replace known companies with sector descriptions
    if _COMPANY_SECTORS:
        for co, sector in sorted(_COMPANY_SECTORS.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(r'\b' + re.escape(co) + r'\b', re.IGNORECASE)
            result = pattern.sub(sector, result)

    # 3. Strip remaining likely proper nouns that aren't known entities
    # (two+ consecutive capitalized words not at sentence start, not agency/place)
    # Keep: agency acronyms, US state/city names, common role words
    _safe_words = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "by", "and",
        "or", "but", "with", "from", "after", "before", "during", "about",
        "new", "old", "federal", "state", "local", "national", "united",
        "north", "south", "east", "west", "president", "governor", "senator",
        "representative", "mayor", "chief", "director", "secretary",
        "department", "agency", "bureau", "commission", "administration",
        "court", "supreme", "district", "appeals",
    }
    _agency_acronyms = {
        "EPA", "FBI", "FEMA", "DHS", "FAA", "NLRB", "ACLU", "NATO", "FDA",
        "CDC", "DOD", "DOE", "HUD", "SEC", "CIA", "NSA", "TSA", "ICE",
        "OSHA", "IRS", "DOJ", "ATF", "DEA", "NTSB", "USDA", "FCC", "FTC",
        "NIH", "NOAA", "NASA", "HHS", "DOT", "WHO", "IMF", "UN", "EU",
    }

    # Replace unknown proper name sequences (e.g., "John Smith") with "an official"
    def _replace_unknown_names(match):
        words = match.group(0).split()
        # Don't replace if it's a known safe pattern or short
        if len(words) < 2:
            return match.group(0)
        for w in words:
            if w.upper() in _agency_acronyms or w.lower() in _safe_words:
                return match.group(0)
        return "an official"

    # Match sequences of 2-3 capitalized words that look like names
    # (not at the very start of text, to avoid replacing sentence starters)
    result = re.sub(
        r'(?<=\s)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})(?=[\s,\.\;\:\'\"])',
        _replace_unknown_names,
        result
    )

    # Clean up any double spaces or awkward phrasing
    result = re.sub(r'\s+', ' ', result).strip()

    return result


def _detect_framing_style(title, summary):
    """
    Detect how a story is framed based on verb patterns and structure.
    Returns: announcement, accusation, revelation, escalation,
             resolution, warning, reaction, or development.
    """
    combined = f"{title} {summary}".lower()

    scores = {}
    for style, keywords in FRAMING_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[style] = score

    if not scores:
        return "development"
    return max(scores, key=scores.get)


def _extract_specifics(title, summary):
    """
    Extract concrete details from headline/summary text.
    Returns dict with numbers, geographic detail, stakes level,
    actor count, and institutional actors.
    """
    combined = f"{title} {summary}"
    combined_lower = combined.lower()

    # Extract numbers (dollar amounts, percentages, counts)
    numbers = []
    # Dollar amounts
    for match in re.finditer(r'\$[\d,.]+\s*(?:billion|million|trillion|thousand|B|M|T)?', combined, re.IGNORECASE):
        numbers.append(match.group(0).strip())
    # Percentages
    for match in re.finditer(r'\d+(?:\.\d+)?%', combined):
        numbers.append(match.group(0))
    # Counts with units
    for match in re.finditer(r'\b(\d{1,6})\s+(people|workers|employees|students|residents|homes|'
                             r'flights|vehicles|patients|deaths|cases|troops|officers|migrants|'
                             r'acres|miles|schools|hospitals|companies|jobs)\b', combined_lower):
        numbers.append(f"{match.group(1)} {match.group(2)}")

    # Geographic detail
    geo = ""
    # US regions
    region_patterns = {
        "Midwest": ["midwest", "ohio", "michigan", "illinois", "indiana", "iowa", "wisconsin", "minnesota"],
        "Southeast": ["southeast", "georgia", "alabama", "florida", "carolina", "tennessee", "mississippi"],
        "Northeast": ["northeast", "new york", "new jersey", "connecticut", "massachusetts", "pennsylvania"],
        "Southwest": ["southwest", "texas", "arizona", "new mexico", "nevada"],
        "West Coast": ["west coast", "california", "oregon", "washington state"],
        "Gulf Coast": ["gulf coast", "louisiana", "mississippi coast"],
        "Pacific Northwest": ["pacific northwest"],
    }
    for region, keywords in region_patterns.items():
        if any(kw in combined_lower for kw in keywords):
            geo = region
            break
    if not geo:
        if any(w in combined_lower for w in ["federal", "washington", "congress", "white house"]):
            geo = "federal/national level"
        elif any(w in combined_lower for w in ["international", "global", "world", "overseas"]):
            geo = "international"

    # Stakes level
    stakes = "medium"
    high_stakes = ["billion", "million", "crisis", "emergency", "death", "killed",
                   "national security", "pandemic", "war", "collapse"]
    low_stakes = ["local", "community", "neighborhood", "school board", "county"]
    critical_stakes = ["trillion", "nuclear", "catastrophe", "mass casualty", "martial law"]

    if any(w in combined_lower for w in critical_stakes):
        stakes = "critical"
    elif any(w in combined_lower for w in high_stakes):
        stakes = "high"
    elif any(w in combined_lower for w in low_stakes):
        stakes = "low"

    # Institutional actors (roles/agencies mentioned)
    actors = set()
    actor_patterns = [
        (r'\b(?:EPA|FBI|FEMA|DHS|FAA|CDC|FDA|DOJ|DOD|SEC|OSHA|NTSB|ATF|DEA|TSA|HHS)\b', "federal agency"),
        (r'\b(?:president|white house|administration)\b', "executive branch"),
        (r'\b(?:senate|congress|house|committee|lawmaker|legislat)\b', "legislature"),
        (r'\b(?:court|judge|ruling|justice)\b', "judiciary"),
        (r'\b(?:governor|state legislat|state attorney)\b', "state government"),
        (r'\b(?:police|sheriff|officer|law enforcement)\b', "law enforcement"),
        (r'\b(?:union|worker|labor|employee)\b', "labor/workers"),
        (r'\b(?:company|corporation|firm|manufacturer|bank)\b', "private sector"),
        (r'\b(?:hospital|doctor|physician|nurse|health system)\b', "healthcare"),
        (r'\b(?:university|school|professor|researcher)\b', "academia"),
    ]
    for pattern, label in actor_patterns:
        if re.search(pattern, combined_lower):
            actors.add(label)

    return {
        "numbers": numbers[:5],  # Cap at 5
        "geographic_detail": geo,
        "stakes_level": stakes,
        "actor_count": len(actors),
        "institutional_actors": list(actors),
    }


def _clean_html(text):
    """Strip HTML tags from RSS descriptions."""
    cleaned = re.sub(r'<[^>]+>', '', text)
    cleaned = re.sub(r'&[a-zA-Z]+;', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()
