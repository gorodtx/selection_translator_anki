from __future__ import annotations

import asyncio
import json

from translate_logic.http import FetchError
from translate_logic.providers.cambridge import (
    parse_cambridge_page,
    translate_cambridge,
)
from translate_logic.providers.google import _parse_google_response


def test_google_variants_are_collected_in_order() -> None:
    payload = json.dumps(
        {
            "sentences": [{"trans": "фраза"}],
            "dict": [{"terms": ["вариант1", "вариант2"]}],
            "alternative_translations": [
                {"alternative_translations": [{"word_postproc": "вариант3"}]}
            ],
        }
    )
    translations = _parse_google_response(payload)
    assert translations[:3] == ["вариант1", "вариант2", "вариант3"]


def test_cambridge_fallback_query_uses_slug() -> None:
    html = """
    <html><body>
      <div class="entry-body__el">
        <span class="ipa dipa">/test/</span>
        <span class="trans" lang="ru">пример</span>
      </div>
    </body></html>
    """

    async def fetcher(url: str) -> str:
        if "q=Hello+world" in url:
            raise FetchError("miss")
        if "q=hello-world" in url:
            return html
        raise FetchError("miss")

    result = asyncio.run(translate_cambridge("Hello world", fetcher))
    assert result.found is True
    assert result.translations == ["пример"]


def test_cambridge_examples_ranked_with_ru_first() -> None:
    html = """
    <html><body>
      <div class="entry-body__el">
        <div class="examp"><span class="eg">Short.</span></div>
        <div class="examp">
          <span class="eg">This is a longer example sentence.</span>
          <span class="trans">Это длинный пример.</span>
        </div>
      </div>
    </body></html>
    """
    data = parse_cambridge_page(html, translation_lang="ru")
    assert data.examples
    assert data.examples[0].ru == "Это длинный пример."
