from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

# Fixed vocabularies (unlike topic/region, not meant to be config-driven extensible)
# for where a post came from and how certain its claims are.
VALID_SOURCE_TYPES = {"club", "federation", "journalist", "outlet"}
VALID_STATUSES = {"confirmed", "rumor"}


@dataclass
class Article:
    source: str  # e.g. "twitter"
    author: str  # e.g. "@AUFOficial"
    url: str
    text: str  # 1-3 sentence body/summary
    published_at: datetime
    topic: str = "other"  # matches a category id in config/topics.yaml
    region: str = "global"  # matches a region id in config/topics.yaml
    headline: str = ""  # short (5-8 word) headline, distinct from `text`
    source_type: str = "outlet"  # club | federation | journalist | outlet
    status: str = "confirmed"  # "confirmed" or "rumor"
    id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.headline:
            self.headline = self.text
        if not self.id:
            basis = self.url or f"{self.author}:{self.text}"
            self.id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
