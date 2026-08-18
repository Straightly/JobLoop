"""Lanes are fully isolated (spec v4 §4).

Each lane owns its own fetch and normalize code outright. Lanes never import
from each other and there is no shared source-adapter layer: two lanes hitting
the same site each carry their own copy. Tuning one lane can then only ever
affect that lane, which is the property the Monday loop depends on.
"""
