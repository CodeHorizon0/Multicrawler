from __future__ import annotations

import random


PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "accept_language": "en-US,en;q=0.9,ru;q=0.8",
    },
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "accept_language": "en-US,en;q=0.9",
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
        "accept_language": "en-US,en;q=0.9,ru;q=0.8",
    },
]


def pick_profile() -> dict[str, str]:
    return dict(random.choice(PROFILES))
