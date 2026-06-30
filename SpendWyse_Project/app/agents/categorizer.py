from typing import Optional


# Ten categories where duplicate subscriptions are common and worth surfacing.
# Match is case-insensitive substring against the merchant name.
# Keep the list tight — false positives erode trust faster than false negatives.
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "streaming_video": [
        "netflix", "disney+", "disney plus", "hulu", "hbo", "max ",
        "peacock", "paramount", "apple tv", "youtube tv",
    ],
    "streaming_music": [
        "spotify", "apple music", "youtube music", "tidal", "pandora",
        "amazon music", "deezer",
    ],
    "cloud_storage": [
        "icloud", "google one", "dropbox", "onedrive", "backblaze", "idrive",
    ],
    "password_manager": [
        "1password", "lastpass", "bitwarden", "dashlane", "keeper security",
    ],
    "ai_tools": [
        "openai", "chatgpt", "anthropic", "claude.ai", "perplexity",
        "midjourney", "github copilot",
    ],
    "news": [
        "nytimes", "new york times", "wsj.com", "wall street journal",
        "washington post", "the atlantic", "substack", "the economist",
    ],
    "fitness": [
        "peloton", "equinox", "planet fitness", "classpass", "strava",
        "fitbod", "apple fitness",
    ],
    "productivity": [
        "notion", "asana", "linear.app", "figma", "adobe", "microsoft 365",
        "office 365", "evernote", "todoist",
    ],
    "gaming": [
        "xbox", "playstation", "nintendo", "steam", "ea play",
    ],
    "food_delivery": [
        "dashpass", "uber one", "grubhub+", "instacart+",
    ],
}


def categorize(merchant: Optional[str]) -> Optional[str]:
    if not merchant:
        return None
    needle = merchant.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for p in patterns:
            if p in needle:
                return category
    return None
