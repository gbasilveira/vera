"""
PIIMaskerMiddleware — mask outbound PII, restore inbound (order=30).

Only runs when ctx.is_external == True (external tool calls).

before_call: Detect PII entities in the payload string values.
  Replace each with a UUID placeholder: <<PII:uuid4>>.
  Persist {call_id -> {uuid: original}} mapping to VFS with 3600s TTL.

after_call:  Load mapping from VFS.
  Replace <<PII:uuid4>> placeholders in the result with original values.
  Delete mapping from VFS.

PII entity types detected: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION,
  US_SSN, CREDIT_CARD, IBAN_CODE, IP_ADDRESS, URL (configurable).
"""
import json
import re
import uuid
from typing import Any

from core.middleware.base import ORDER_PII, PIIMaskError, PIISwapError, ToolCallContext, VeraMiddleware


# Lazy-load Presidio to avoid slow import at module level
_analyzer = None
_anonymizer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine
        _analyzer = AnalyzerEngine()
    return _analyzer


def _get_anonymizer():
    global _anonymizer
    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()
    return _anonymizer


PII_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION",
    "US_SSN", "CREDIT_CARD", "IP_ADDRESS",
]
PII_PLACEHOLDER_PATTERN = re.compile(r"<<PII:([a-zA-Z0-9-]+)>>")


def _mask_string(text: str, mapping: dict) -> str:
    """Detect and replace PII in text. Updates mapping in-place."""
    try:
        analyzer = _get_analyzer()
        results = analyzer.analyze(text=text, language="en", entities=PII_ENTITIES)
        if not results:
            return text
        # Replace from right to left to preserve offsets
        for r in sorted(results, key=lambda x: x.start, reverse=True):
            pii_uuid = str(uuid.uuid4())
            original = text[r.start:r.end]
            placeholder = f"<<PII:{pii_uuid}>>"
            text = text[:r.start] + placeholder + text[r.end:]
            mapping[pii_uuid] = original
        return text
    except Exception as e:
        raise PIIMaskError(f"PII masking failed: {e}") from e


def _unmask_string(text: str, mapping: dict) -> str:
    """Replace <<PII:uuid>> placeholders with original values."""
    def replacer(match):
        pii_uuid = match.group(1)
        return mapping.get(pii_uuid, match.group(0))  # Leave as-is if not in mapping
    return PII_PLACEHOLDER_PATTERN.sub(replacer, text)


def _mask_dict_values(d: dict, mapping: dict) -> dict:
    """Recursively mask PII in all string values of a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _mask_string(v, mapping)
        elif isinstance(v, dict):
            result[k] = _mask_dict_values(v, mapping)
        elif isinstance(v, list):
            result[k] = [_mask_string(i, mapping) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


def _unmask_dict_values(d: dict, mapping: dict) -> dict:
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _unmask_string(v, mapping)
        elif isinstance(v, dict):
            result[k] = _unmask_dict_values(v, mapping)
        elif isinstance(v, list):
            result[k] = [_unmask_string(i, mapping) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


class PIIMaskerMiddleware(VeraMiddleware):
    name = "pii_masker"
    order = ORDER_PII

    _VFS_TTL = 3600  # 1 hour

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        if not ctx.is_external:
            return ctx  # Internal tools: skip masking

        mapping: dict[str, str] = {}
        try:
            masked_payload = _mask_dict_values(ctx.payload, mapping)
        except PIIMaskError:
            raise
        except Exception as e:
            raise PIIMaskError(f"Unexpected error during PII masking: {e}") from e

        if mapping:
            vfs_key = f"pii:mapping:{ctx.call_id}"
            await ctx.vfs.set(vfs_key, json.dumps(mapping).encode(), ttl=self._VFS_TTL)
            await ctx.bus.emit("pii.mask_applied", {
                "call_id": ctx.call_id,
                "field_count": len(mapping),
            })

        return ctx.with_payload(masked_payload)

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        if not ctx.is_external:
            return result

        vfs_key = f"pii:mapping:{ctx.call_id}"
        raw = await ctx.vfs.get(vfs_key)
        if raw is None:
            return result  # No mapping stored — nothing to unmask

        try:
            mapping = json.loads(raw.decode())
        except Exception as e:
            raise PIISwapError(f"Failed to load PII mapping from VFS: {e}") from e

        await ctx.vfs.delete(vfs_key)
        await ctx.bus.emit("pii.unmask_applied", {"call_id": ctx.call_id})

        if isinstance(result, dict):
            return _unmask_dict_values(result, mapping)
        elif isinstance(result, str):
            return _unmask_string(result, mapping)
        elif isinstance(result, list):
            return [_unmask_string(i, mapping) if isinstance(i, str) else i for i in result]
        return result

    async def on_error(self, ctx: ToolCallContext, error: Exception) -> None:
        # Clean up VFS mapping on error
        if ctx.is_external:
            vfs_key = f"pii:mapping:{ctx.call_id}"
            await ctx.vfs.delete(vfs_key)