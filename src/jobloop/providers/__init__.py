"""Concrete LLM provider adapters implementing `jobloop.core.llm.Scorer`.

Spec v4 §9: "adapters are optional install extras." None currently need an
extra install -- like the USAJOBS adapter, each one calls its provider's
REST API directly over stdlib `urllib`, consistent with this repo's
zero-runtime-dependency rule. A future provider that genuinely needs a
third-party SDK would be the first exception, not the pattern.
"""
