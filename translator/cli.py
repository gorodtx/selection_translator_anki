from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from translate_logic.application.translate import translate_async
from translate_logic.language_base.provider import (
    LanguageBaseProvider,
    default_fallback_language_base_path,
    default_language_base_path,
)
from translate_logic.language_base.multi_provider import MultiLanguageBaseProvider
from translate_logic.models import TranslationResult, TranslationVariant
from translate_logic.providers.opus_mt import OpusMtProvider, default_opus_mt_model_dir

DEFAULT_SOURCE = "en"
DEFAULT_TARGET = "ru"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI smoke tests for offline translation pipeline."
    )
    parser.add_argument("text", help="Text/word/phrase to translate.")
    parser.add_argument(
        "--provider",
        choices=("pipeline", "opus"),
        default="pipeline",
        help="Select provider to test.",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument(
        "--format",
        choices=("lines", "json"),
        default="lines",
        help="Output format.",
    )
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


def _variant_payload(variant: TranslationVariant) -> dict[str, object]:
    return {
        "ru": variant.ru,
        "pos": variant.pos,
        "synonyms": list(variant.synonyms),
        "examples": [{"en": item.en, "ru": item.ru} for item in variant.examples],
    }


def _print_json(result: TranslationResult) -> None:
    payload = {
        "status": result.status.value,
        "translation_ru": result.translation_ru.text,
        "example_en": result.example_en.text,
        "example_ru": result.example_ru.text,
        "variants": [_variant_payload(variant) for variant in result.variants],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_lines(result: TranslationResult) -> None:
    if not result.variants:
        print("variants:")
        return
    print("variants:")
    for idx, variant in enumerate(result.variants, start=1):
        print(f"{idx}. {variant.ru}")
        if variant.pos:
            print(f"  pos: {variant.pos}")
        if variant.synonyms:
            print(f"  synonyms: {', '.join(variant.synonyms)}")
        for example_index, example in enumerate(variant.examples, start=1):
            print(f"  en{example_index}: {example.en}")
            print(f"  ru{example_index}: {example.ru}")


async def _run_pipeline(
    text: str,
    source: str,
    target: str,
    language_db: Path,
    fallback_language_db: Path,
) -> TranslationResult:
    opus_provider = OpusMtProvider(model_dir=default_opus_mt_model_dir())
    language_base = MultiLanguageBaseProvider(
        primary=LanguageBaseProvider(db_path=language_db),
        fallback=LanguageBaseProvider(db_path=fallback_language_db),
    )
    return await translate_async(
        text,
        source,
        target,
        opus_provider=opus_provider,
        language_base=language_base,
    )


def _run_opus(text: str, source: str, target: str) -> TranslationResult:
    provider = OpusMtProvider(model_dir=default_opus_mt_model_dir())
    translations = provider.translate_variants(text, source, target, limit=3)
    if not translations:
        return TranslationResult.empty()
    variants = tuple(
        TranslationVariant(
            ru=item,
            pos=None,
            synonyms=(),
            examples=(),
        )
        for item in translations
    )
    return TranslationResult(variants=variants)


def main() -> int:
    args = _build_parser().parse_args()

    if args.provider == "pipeline":
        result = asyncio.run(
            _run_pipeline(
                args.text,
                args.source,
                args.target,
                args.language_db,
                args.fallback_language_db,
            )
        )
    else:
        result = _run_opus(args.text, args.source, args.target)

    if args.format == "json":
        _print_json(result)
    else:
        _print_lines(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
