"""
Scraper Agent — Pulls real news shape/topics to inform fictional story generation.

Doesn't copy real stories — mimics format, topic weight, and emotional register
from current real-world news to keep fictional output feeling timely.
"""

import feedparser
import json
from datetime import datetime


# RSS feeds to sample for news shape
RSS_FEEDS = [
    "https://news.google.com/rss",
    "https://rss.app/feeds/t/AP-Top-News/8BZ2MHPF8JR4g1bG.xml",
]


def scrape_news_context():
    """
    Pull headlines from RSS feeds and extract:
    - Trending topics
    - Emotional register (calm/tense/chaotic/optimistic)
    - Dominant story formats

    Returns a dict consumed by the writer agent.
    """
    headlines = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:15]:
                headlines.append(entry.get("title", ""))
        except Exception as e:
            print(f"  Warning: Could not fetch {feed_url}: {e}")

    # Keyword-based topic classification
    topic_counts = {
        "politics": 0,
        "infrastructure": 0,
        "science": 0,
        "crime": 0,
        "international": 0,
        "economy": 0,
        "weather": 0,
    }

    politics_keywords = ["president", "senate", "congress", "vote", "election", "bill", "governor", "legislation", "party", "democrat", "republican"]
    infra_keywords = ["bridge", "road", "rail", "transit", "port", "construction", "highway", "pipeline", "grid"]
    science_keywords = ["study", "research", "nasa", "climate", "species", "medical", "vaccine", "ai", "technology"]
    crime_keywords = ["arrest", "shooting", "murder", "police", "fbi", "fraud", "trial", "sentenced", "charges"]
    intl_keywords = ["ukraine", "china", "eu", "nato", "united nations", "foreign", "trade", "tariff", "summit"]
    economy_keywords = ["market", "stock", "inflation", "jobs", "unemployment", "fed", "interest rate", "gdp", "recession"]
    weather_keywords = ["storm", "hurricane", "tornado", "flood", "wildfire", "drought", "snow", "heat wave"]

    for headline in headlines:
        h = headline.lower()
        for kw in politics_keywords:
            if kw in h:
                topic_counts["politics"] += 1
                break
        for kw in infra_keywords:
            if kw in h:
                topic_counts["infrastructure"] += 1
                break
        for kw in science_keywords:
            if kw in h:
                topic_counts["science"] += 1
                break
        for kw in crime_keywords:
            if kw in h:
                topic_counts["crime"] += 1
                break
        for kw in intl_keywords:
            if kw in h:
                topic_counts["international"] += 1
                break
        for kw in economy_keywords:
            if kw in h:
                topic_counts["economy"] += 1
                break
        for kw in weather_keywords:
            if kw in h:
                topic_counts["weather"] += 1
                break

    # Determine dominant topics (top 3)
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    trending = [t[0] for t in sorted_topics[:3] if t[1] > 0]
    if not trending:
        trending = ["politics", "economy", "infrastructure"]

    # Simple register heuristic
    urgent_words = ["breaking", "emergency", "crisis", "killed", "shooting", "attack", "war", "collapse"]
    calm_words = ["announces", "plans", "report", "study", "expected", "scheduled"]
    all_text = " ".join(headlines).lower()

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

    # Determine dominant formats
    formats = ["anchor_read"]
    if urgent_count > 2:
        formats.append("breaking")
    if any("report" in h.lower() for h in headlines):
        formats.append("field_report")

    context = {
        "trending_topics": trending,
        "register": register,
        "dominant_formats": formats,
        "headline_count": len(headlines),
        "timestamp": datetime.now().isoformat(),
    }

    print(f"  Scraped {len(headlines)} headlines. Register: {register}. Topics: {trending}")
    return context
