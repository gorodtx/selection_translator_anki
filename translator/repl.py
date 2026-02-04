from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from translate_logic.application.translate import translate_async
from translate_logic.language_base.provider import (
    LanguageBaseProvider,
    default_fallback_language_base_path,
    default_language_base_path,
)
from translate_logic.language_base.multi_provider import MultiLanguageBaseProvider
from translate_logic.models import TranslationResult
from translate_logic.providers.opus_mt import OpusMtProvider, default_opus_mt_model_dir

DEFAULT_SOURCE = "en"
DEFAULT_TARGET = "ru"


def _print_lines(result: TranslationResult) -> None:
    if not result.variants:
        print("variants:\n")
        return
    print("variants:")
    for idx, variant in enumerate(result.variants, start=1):
        print(f"{idx}. {variant.ru}")
        for example_index, example in enumerate(variant.examples, start=1):
            print(f"  en{example_index}: {example.en}")
            print(f"  ru{example_index}: {example.ru}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive REPL for the offline translation pipeline (keeps models in memory)."
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument(
        "--language-db",
        type=Path,
        default=default_language_base_path(),
        help="Primary SQLite language base (examples) path.",
    )
    parser.add_argument(
        "--fallback-language-db",
        type=Path,
        default=default_fallback_language_base_path(),
        help="Fallback SQLite language base (examples) path.",
    )
    return parser


async def _translate_once(
    text: str,
    source: str,
    target: str,
    opus_provider: OpusMtProvider,
    language_base: MultiLanguageBaseProvider,
) -> TranslationResult:
    return await translate_async(
        text,
        source,
        target,
        opus_provider=opus_provider,
        language_base=language_base,
    )


def main() -> int:
    args = _build_parser().parse_args()

    opus_provider = OpusMtProvider(model_dir=default_opus_mt_model_dir())
    language_base = MultiLanguageBaseProvider(
        primary=LanguageBaseProvider(db_path=args.language_db),
        fallback=LanguageBaseProvider(db_path=args.fallback_language_db),
    )

    print("translator repl: enter text to translate, or 'quit' to exit.")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            print("")
            break
        if not text:
            continue
        if text.casefold() in {"q", "quit", "exit"}:
            break
        result = asyncio.run(
            _translate_once(
                text,
                args.source,
                args.target,
                opus_provider,
                language_base,
            )
        )
        _print_lines(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
