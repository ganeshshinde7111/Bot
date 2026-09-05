"""Lightweight news-sentiment tool. Uses NewsAPI.org (or any compatible
headline API) when NEWS_API_KEY is set, and falls back to a local VADER
lexicon score so the tool still degrades gracefully offline in a VPS
with restricted egress.
"""

import requests
from mcp.server.fastmcp import FastMCP
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from ..config import settings

_analyzer = SentimentIntensityAnalyzer()


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_news_sentiment(query: str, max_articles: int = 10) -> dict:
        """Fetch recent headlines for `query` (a company/ticker/topic name)
        and return a compound sentiment score in [-1, 1] plus the
        headlines used, so Claude can factor news tone into a signal
        without hallucinating articles it never saw."""
        if not settings.NEWS_API_KEY:
            return {
                "error": "NEWS_API_KEY not set -- sentiment analysis unavailable.",
                "compound_score": None,
            }

        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": max_articles,
                "apiKey": settings.NEWS_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])

        scored = []
        total = 0.0
        for a in articles:
            headline = a.get("title") or ""
            score = _analyzer.polarity_scores(headline)["compound"]
            total += score
            scored.append({"headline": headline, "score": round(score, 3), "url": a.get("url")})

        avg = round(total / len(scored), 3) if scored else 0.0
        label = "bullish" if avg > 0.15 else "bearish" if avg < -0.15 else "neutral"

        return {"query": query, "compound_score": avg, "label": label, "articles": scored}
