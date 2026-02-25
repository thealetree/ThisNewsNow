"""
Scraper Agent — Pulls real news shape, topics, and story structures
to inform fictional story generation.

Grabs headlines + summaries from major RSS feeds, extracts the "shape"
of what's actually happening in the world (topics, conflict types,
geographic focus, stakes level, emotional register), and passes this
as inspiration to the writer. Never copies verbatim — the writer uses
these signals to craft adjacent but entirely fictional stories.
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


def scrape_news_context():
    """
    Pull headlines + summaries from RSS feeds and extract:
    - Trending topics (weighted)
    - Emotional register (calm/tense/chaotic/optimistic)
    - Story shapes: brief descriptions of real story patterns
    - Conflict types currently active in the news

    Returns a dict consumed by the writer agent.
    """
    stories_raw = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            # Use requests for SSL compatibility, then parse with feedparser
            resp = requests.get(feed_url, timeout=10, headers={
                "User-Agent": "ThisNewsNow/1.0 (RSS Reader)"
            })
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:12]:
                title = entry.get("title", "").strip()
                summary = ""
                if entry.get("summary"):
                    summary = _clean_html(entry["summary"])[:300]
                elif entry.get("description"):
                    summary = _clean_html(entry["description"])[:300]

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

    # ── Build story shapes ──
    # These are abstract summaries of what's in the news right now,
    # stripped of specific names/companies so the writer can riff
    story_shapes = _extract_story_shapes(stories_raw[:20])

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
        "story_shapes": story_shapes,
        "headline_count": len(headlines),
        "timestamp": datetime.now().isoformat(),
    }

    print(f"  Scraped {len(headlines)} headlines. Register: {register}. "
          f"Topics: {trending}. Conflicts: {conflict_types}")
    if story_shapes:
        print(f"  Story shapes: {len(story_shapes)} extracted")

    return context


def _extract_story_shapes(stories):
    """
    Extract abstract 'story shapes' from real headlines/summaries.

    A story shape captures the structure and topic without specific
    real-world names, so the writer can create adjacent fiction.
    Example: "Environmental agency investigating water contamination
    in a mid-size industrial city" (no actual city/person names).
    """
    shapes = []
    seen_topics = set()

    for story in stories:
        title = story["title"]
        summary = story.get("summary", "")
        combined = f"{title} {summary}".lower()

        # Determine the topic
        topic = None
        for t, keywords in TOPIC_KEYWORDS.items():
            if any(kw in combined for kw in keywords):
                topic = t
                break
        if not topic:
            continue

        # Determine conflict type
        conflict = "development"
        for ctype, keywords in CONFLICT_PATTERNS.items():
            if any(kw in combined for kw in keywords):
                conflict = ctype
                break

        # Build an abstract shape description
        shape_key = f"{topic}_{conflict}"
        if shape_key in seen_topics:
            continue
        seen_topics.add(shape_key)

        shape = _abstract_headline(title, summary, topic, conflict)
        if shape:
            shapes.append(shape)

        if len(shapes) >= 6:
            break

    return shapes


def _abstract_headline(title, summary, topic, conflict):
    """
    Create an abstract description of a story's shape.
    Strips real names and specific details, keeps structure.
    """
    # Use topic + conflict as the core shape
    topic_labels = {
        "politics": "political",
        "infrastructure": "infrastructure",
        "science": "scientific/research",
        "crime": "law enforcement",
        "international": "international affairs",
        "economy": "economic",
        "weather": "weather/disaster",
        "health": "public health",
        "environment": "environmental",
    }

    conflict_labels = {
        "standoff": "with ongoing disagreement between officials",
        "crisis": "with escalating urgency and public concern",
        "investigation": "involving an active investigation or audit",
        "protest": "with public demonstrations or labor action",
        "development": "with new announcements or policy changes",
        "tragedy": "involving casualties or significant harm",
        "legal": "with court proceedings or legal challenges",
    }

    topic_label = topic_labels.get(topic, topic)
    conflict_label = conflict_labels.get(conflict, "")

    # Extract any geographic hints (state/city patterns) without specific names
    geo_hint = ""
    combined = f"{title} {summary}"
    if any(w in combined.lower() for w in ["state", "county", "city", "town", "region"]):
        geo_hint = " in a US region"
    elif any(w in combined.lower() for w in ["capitol", "washington", "federal", "congress"]):
        geo_hint = " at the federal level"

    return f"A {topic_label} story {conflict_label}{geo_hint}. " \
           f"Inspired by: {title[:80]}"


def _clean_html(text):
    """Strip HTML tags from RSS descriptions."""
    cleaned = re.sub(r'<[^>]+>', '', text)
    cleaned = re.sub(r'&[a-zA-Z]+;', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()
