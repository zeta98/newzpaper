from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    source: str  # e.g. "twitter"
    author: str  # e.g. "@AUFOficial"
    url: str
    text: str
    published_at: datetime
    topic: str = "other"  # matches a category id in config/topics.yaml
    region: str = "global"  # matches a region id in config/topics.yaml
    id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.id:
            basis = self.url or f"{self.author}:{self.text}"
            self.id = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
