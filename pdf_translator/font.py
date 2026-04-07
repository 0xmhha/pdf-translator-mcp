"""Font download and management for PDF translation output."""

import logging
from pathlib import Path

from babeldoc.assets.assets import get_font_and_metadata

logger = logging.getLogger(__name__)

NOTO_NAME = "noto"

NOTO_LANG_LIST = [
    "am", "ar", "bn", "bg", "chr", "el", "gu", "iw", "hi", "kn",
    "ml", "mr", "ru", "sr", "ta", "te", "th", "ur", "uk",
]

LANG_FONT_MAP = {
    **{la: "GoNotoKurrent-Regular.ttf" for la in NOTO_LANG_LIST},
    **{
        la: f"SourceHanSerif{region}-Regular.ttf"
        for region, langs in {
            "CN": ["zh-cn", "zh-hans", "zh"],
            "TW": ["zh-tw", "zh-hant"],
            "JP": ["ja"],
            "KR": ["ko"],
        }.items()
        for la in langs
    },
}

LANG_LINEHEIGHT_MAP = {
    "ja": 1.1, "ko": 1.4, "en": 1.2, "ar": 1.0,
    "ru": 0.8, "uk": 0.8, "ta": 0.8,
}


def download_font(lang: str) -> str:
    """Download and return the path to the appropriate font for the target language."""
    lang = lang.lower()
    font_name = LANG_FONT_MAP.get(lang, "GoNotoKurrent-Regular.ttf")

    font_path = Path("/app") / font_name
    if not font_path.exists():
        font_path, _ = get_font_and_metadata(font_name)
        font_path = font_path.as_posix()
    else:
        font_path = font_path.as_posix()

    logger.info(f"Using font: {font_path}")
    return font_path


def get_line_height(lang: str) -> float:
    """Get default line height multiplier for the target language."""
    return LANG_LINEHEIGHT_MAP.get(lang.lower(), 1.1)
