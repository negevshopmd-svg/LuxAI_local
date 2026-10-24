"""Bounded parsing of model JSON proposals; never execute or repair code.

Providers sometimes wrap an otherwise valid JSON object in prose or markdown.
Accept those presentation wrappers, but keep JSON syntax and value types strict.
Action-specific validation still belongs to the executor's schema validator.
"""
from __future__ import annotations

import json
import math
import re

MAX_MODEL_JSON_CHARS = 65_536
MAX_MODEL_JSON_DEPTH = 32
MAX_TEXT_BLOCKS = 128


class ModelJSONError(ValueError):
    """The model did not return one bounded, unambiguous JSON object."""


_CODE_WRAPPER = re.compile(
    r"(?:^|[;\n])\s*(?:const|let|var|return|function|import|from|def|class|"
    r"lambda|if|for|while|try|raise)\b|=>|</?script\b|[=;]",
    re.IGNORECASE,
)


def _text_content(content, max_chars):
    if isinstance(content, list):
        if len(content) > MAX_TEXT_BLOCKS:
            raise ModelJSONError("Too many provider text blocks")
        pieces = []
        length = 0
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            value = block.get("text", "")
            if not isinstance(value, str):
                raise ModelJSONError("Provider text block is not text")
            length += len(value)
            if length > max_chars:
                raise ModelJSONError("Model JSON response exceeds the size limit")
            pieces.append(value)
        content = "".join(pieces)
    if not isinstance(content, str) or not content.strip():
        raise ModelJSONError("Model returned no JSON text")
    if len(content) > max_chars:
        raise ModelJSONError("Model JSON response exceeds the size limit")
    return content.strip().removeprefix("\ufeff").lstrip()


def _object_end(text, start=0):
    """Find the first balanced object boundary, ignoring quoted JSON text."""
    stack = []
    quoted = escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
            if len(stack) > MAX_MODEL_JSON_DEPTH:
                raise ModelJSONError("Model JSON nesting exceeds the limit")
        elif char in "}]":
            if not stack or (stack.pop(), char) not in {("{", "}"), ("[", "]")}:
                raise ModelJSONError("Model JSON has mismatched containers")
            if not stack:
                return index + 1
    raise ModelJSONError("Model JSON object is incomplete")


def _check_wrapper(text):
    # Never interpret a JavaScript/Python assignment, function or code block as
    # prose. A second object is ambiguous even if the first one looks valid.
    if (any(char in text for char in "{}[]`") or _CODE_WRAPPER.search(text)
            or re.fullmatch(r"\s*(?:true|false|null|-?\d+(?:\.\d+)?)\s*", text)):
        raise ModelJSONError("Model response contains code or multiple JSON values")


def _payload(text):
    if text.startswith(("[", '"')):
        raise ModelJSONError("Model must return a JSON object")
    start = text.find("{")
    fence = text.find("```")
    if start >= 0 and (fence < 0 or start < fence):
        _check_wrapper(text[:start])
        end = _object_end(text, start)
        _check_wrapper(text[end:])
        return text[start:end]
    if "```" in text:
        first = fence
        last = text.rfind("```")
        if last == first:
            raise ModelJSONError("Model JSON fence is incomplete or ambiguous")
        _check_wrapper(text[:first])
        _check_wrapper(text[last + 3:])
        body = text[first + 3:last].strip()
        if re.match(r"(?i)^json(?:\s|\{|$)", body):
            body = body[4:].lstrip()
        elif not body.startswith("{"):
            raise ModelJSONError("Only JSON markdown fences are accepted")
        # A JSON fence must contain JSON alone, not executable code or prose.
        if not body.startswith("{"):
            raise ModelJSONError("Model must return a JSON object")
        end = _object_end(body)
        if body[end:].strip():
            raise ModelJSONError("JSON fence contains trailing content")
        return body

    raise ModelJSONError("Model must return a JSON object")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelJSONError("Model JSON contains duplicate object keys")
        result[key] = value
    return result


def _reject_constant(value):
    raise ModelJSONError("Non-finite numbers are not valid model JSON")


def _check_numbers(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ModelJSONError("Non-finite numbers are not valid model JSON")
    if isinstance(value, dict):
        for child in value.values():
            _check_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _check_numbers(child)


def _quote_bare_object_keys(text):
    """Quote ASCII identifier keys outside strings, leaving values untouched.

    This scanner is deliberately not a JavaScript/Python parser. Strict JSON
    decoding still validates the complete result, duplicate keys and types.
    """
    result, stack = [], []
    quoted = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            if stack and stack[-1][0] == "{":
                stack[-1][1] = False
        elif char in "{[":
            stack.append([char, char == "{"])
        elif char in "}]":
            stack.pop()  # _payload has already checked balanced containers.
        elif char == "," and stack:
            stack[-1][1] = stack[-1][0] == "{"
        elif char == ":" and stack:
            stack[-1][1] = False
        elif stack and stack[-1] == ["{", True] and (char.isascii() and (char.isalpha() or char == "_")):
            end = index + 1
            while end < len(text) and text[end].isascii() and (text[end].isalnum() or text[end] == "_"):
                end += 1
            colon = end
            while colon < len(text) and text[colon].isspace():
                colon += 1
            if end - index <= 41 and colon < len(text) and text[colon] == ":":
                result.append('"' + text[index:end] + '"')
                stack[-1][1] = False
                index = end
                continue
        result.append(char)
        index += 1
    value = "".join(result)
    if len(value) > MAX_MODEL_JSON_CHARS:
        raise ModelJSONError("Repaired model JSON exceeds the size limit")
    return value


def parse_model_json(content, *, max_chars=MAX_MODEL_JSON_CHARS, quote_bare_keys=False) -> dict:
    """Extract one strict JSON object from a provider's text response.

    Syntax is strict by default. ``quote_bare_keys`` optionally repairs only
    unquoted ASCII identifier object keys; single quotes, trailing commas,
    executable code and Python values remain invalid. No value is coerced.
    Errors deliberately omit the response body, which may include private text.
    """
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_MODEL_JSON_CHARS:
        raise ValueError("Invalid model JSON size limit")
    if type(quote_bare_keys) is not bool:
        raise ValueError("Bare key repair flag must be a boolean")
    payload = _payload(_text_content(content, max_chars))
    try:
        try:
            result = json.loads(payload, object_pairs_hook=_unique_object,
                                parse_constant=_reject_constant)
        except json.JSONDecodeError:
            if not quote_bare_keys:
                raise
            result = json.loads(_quote_bare_object_keys(payload), object_pairs_hook=_unique_object,
                                parse_constant=_reject_constant)
    except ModelJSONError:
        raise
    except (ValueError, RecursionError, OverflowError):
        raise ModelJSONError("Model returned invalid JSON syntax") from None
    if not isinstance(result, dict):
        raise ModelJSONError("Model must return a JSON object")
    _check_numbers(result)
    return result
