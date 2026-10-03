"""Thin Gemini wrapper with JSON output, on-disk replay cache, retry, and cost/latency accounting.

Env:
  GEMINI_API_KEY (or GOOGLE_API_KEY)   required for live calls
  AIP_GEMINI_MODEL                     default "gemini-3.1-pro-preview"
  AIP_PRICE_IN_PER_M / AIP_PRICE_OUT_PER_M   USD per 1M tokens (override the table below; check current pricing)
  AIP_LLM_CACHE                        cache dir (default .llm_cache); set to "" to disable

Cache entries store the original token counts and latency, so replaying a run from cache reports the
same cost/latency numbers a fresh run would (cache hits are counted separately).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "gemini-3.1-pro-preview"
# USD per 1M tokens (input, output) -- list-price assumption for <=200k-token prompts; verify before quoting costs.
# NOTE: no verified price for gemini-3.1-pro-preview is hard-coded; unknown models fall back to the 2.5-pro list price
# below as a PLACEHOLDER. Set AIP_PRICE_IN_PER_M / AIP_PRICE_OUT_PER_M from Google's pricing page for real cost numbers.
PRICE_TABLE = {
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
}


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_seconds: float = 0.0          # sum of per-call latencies (original latencies for cache hits)
    parse_failures: int = 0
    by_tag: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, tag, it, ot, cost, secs, cached):
        with self._lock:
            self._add(tag, it, ot, cost, secs, cached)

    def _add(self, tag, it, ot, cost, secs, cached):
        self.calls += 1
        self.cache_hits += int(cached)
        self.input_tokens += it
        self.output_tokens += ot
        self.cost_usd += cost
        self.llm_seconds += secs
        t = self.by_tag.setdefault(tag, dict(calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0))
        t["calls"] += 1
        t["input_tokens"] += it
        t["output_tokens"] += ot
        t["cost_usd"] += cost

    def as_meta(self) -> dict:
        return dict(llm_calls=self.calls, llm_cache_hits=self.cache_hits, input_tokens=self.input_tokens,
                    output_tokens=self.output_tokens, cost_usd=round(self.cost_usd, 6),
                    llm_seconds=round(self.llm_seconds, 3), llm_parse_failures=self.parse_failures,
                    llm_by_stage=self.by_tag)


def parse_json(text: str):
    """Tolerant JSON extraction (handles ```json fences and leading/trailing prose)."""
    if text is None:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", t, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


class LLMClient:
    """Base: subclasses implement _call(system, prompt) -> (text, in_tokens, out_tokens)."""
    model = "abstract"

    def __init__(self):
        self.stats = LLMStats()

    def _call(self, system: str, prompt: str):
        raise NotImplementedError

    def price(self):
        env_in, env_out = os.getenv("AIP_PRICE_IN_PER_M"), os.getenv("AIP_PRICE_OUT_PER_M")
        if env_in and env_out:
            return float(env_in), float(env_out)
        return PRICE_TABLE.get(self.model, PRICE_TABLE["gemini-2.5-pro"])

    def generate_json(self, prompt: str, system: str = "", tag: str = "misc"):
        """Returns parsed JSON (or None on unparseable output)."""
        text, it, ot, secs, cached = self._cached_call(system, prompt)
        pin, pout = self.price()
        self.stats.add(tag, it, ot, it / 1e6 * pin + ot / 1e6 * pout, secs, cached)
        obj = parse_json(text)
        if obj is None:
            # unparseable (e.g. output truncated at the token limit): retry once, bypassing/overwriting the cached bad answer
            with self.stats._lock:
                self.stats.parse_failures += 1
            print(f"  [llm] unparseable response ({tag}); retrying once", file=sys.stderr, flush=True)
            text, it, ot, secs, cached = self._cached_call(system, prompt, refresh=True)
            self.stats.add(tag, it, ot, it / 1e6 * pin + ot / 1e6 * pout, secs, cached)
            obj = parse_json(text)
        return obj

    # -- cache -------------------------------------------------------------
    def _cache_path(self, system, prompt) -> Optional[Path]:
        d = os.getenv("AIP_LLM_CACHE", ".llm_cache")
        if not d:
            return None
        h = hashlib.sha256(json.dumps([self.model, system, prompt]).encode()).hexdigest()
        return Path(d) / f"{h}.json"

    def _cached_call(self, system, prompt, refresh=False):
        cp = self._cache_path(system, prompt)
        if cp and cp.exists() and not refresh:
            e = json.loads(cp.read_text())
            return e["text"], e["in"], e["out"], e["secs"], True
        t0 = time.perf_counter()
        last = None
        for attempt in range(4):
            try:
                text, it, ot = self._call(system, prompt)
                break
            except LLMUnavailable:
                raise
            except Exception as e:                 # rate limits / transient network
                last = e
                print(f"  [llm] attempt {attempt + 1} failed: {str(e)[:200]}", file=sys.stderr, flush=True)
                msg = str(e)
                if any(k in msg for k in ("API key", "API_KEY", "PERMISSION_DENIED", "NOT_FOUND", "404", "INVALID_ARGUMENT", "400")):
                    break                           # permanent error (bad key / unknown model): do not retry
                time.sleep(2 ** (attempt + 1))
        else:
            raise RuntimeError(f"LLM call failed after retries: {last}")
        secs = time.perf_counter() - t0
        print(f"  [llm] {self.model} call done in {secs:.1f}s ({it} in / {ot} out tokens)", file=sys.stderr, flush=True)
        if cp:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(dict(text=text, **{"in": it, "out": ot, "secs": secs})))
        return text, it, ot, secs, False


class GeminiClient(LLMClient):
    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        super().__init__()
        self.model = model or os.getenv("AIP_GEMINI_MODEL", DEFAULT_MODEL)
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY not set")
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMUnavailable("pip install google-genai") from e
        self._types = types
        timeout_ms = int(float(os.getenv("AIP_LLM_TIMEOUT_S", "600")) * 1000)
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_ms))

    def _call(self, system, prompt):
        cfg = self._types.GenerateContentConfig(
            system_instruction=system or None, temperature=0.0, response_mime_type="application/json")
        r = self._client.models.generate_content(model=self.model, contents=prompt, config=cfg)
        u = r.usage_metadata
        it = getattr(u, "prompt_token_count", 0) or 0
        # thinking tokens are billed as output
        ot = (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return r.text, it, ot


class UnavailableClient(LLMClient):
    """Used when no key is configured: every call raises so callers can degrade and log."""
    model = "unavailable"

    def __init__(self, reason="GEMINI_API_KEY not set"):
        super().__init__()
        self.reason = reason

    def _call(self, system, prompt):
        raise LLMUnavailable(self.reason)

    def generate_json(self, prompt, system="", tag="misc"):
        raise LLMUnavailable(self.reason)


class ScriptedClient(LLMClient):
    """Test double: fn(system, prompt) -> python object (serialised to JSON). Not used for reported results."""
    model = "scripted"

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def _cache_path(self, system, prompt):
        return None

    def _call(self, system, prompt):
        return json.dumps(self.fn(system, prompt)), len(prompt) // 4, 50


def default_client() -> LLMClient:
    try:
        return GeminiClient()
    except LLMUnavailable as e:
        return UnavailableClient(str(e))
