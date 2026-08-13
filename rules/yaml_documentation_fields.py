#!/usr/bin/env python3
"""Detect YAML lines that belong to documentation fields (`description`,
`example`, `examples`), including nested descendants and multi-document
streams.

Used by ``rules/no_image_tags.py`` to downgrade tagged-image lines that are
just prose/sample text in an OpenAPI-style schema, not a real runtime field.

## Design: ``yaml.parse()`` event stream

This module walks PyYAML's low-level event stream (``SafeLoader``), not a
composed node tree. That keeps each alias (``*x``) as an independent
reference site — never merged into the same object as its anchor (``&x``) —
so documentation status can be decided per occurrence. Nesting is tracked
with an explicit stack (no recursive walk of composed nodes), and cost stays
linear in the number of events plus the size of a small per-document alias
graph.

## Anchor / alias safety

A tagged image defined under a documentation field and reused at a real
runtime site must not be downgraded to ``info``. The alias/merge site often
has no image text for the line scanner to see:

    description: &img quay.io/org/real-image:v1.2.3
    containers:
      - image: *img

Every docs-field scalar contribution records the open anchor names that
enclose it (and its own anchor, if any). Any alias seen outside a
documentation field marks that name as tainted. At each document end, taint
expands by BFS over in-docs alias edges (so a docs-anchored structure that
itself references the image anchor also taints it when merged outside), and
pending contributions whose anchors intersect the tainted set are dropped.

Open anchors use a parent-linked chain: each frame stores only its own
anchor plus a pointer to the parent chain (O(1) to push a frame). Anchor
names are materialized only when recording pending lines or alias edges.

YAML anchors are per-document. Outside-docs taint and the in-docs alias
graph are finalized and cleared on each ``DocumentEndEvent``, so an alias
in document A cannot affect a same-named anchor in document B.

## Schema keyword collisions

A CRD/API property may itself be named ``description`` / ``example`` /
``examples``. Its schema ``default`` / ``enum`` / ``const`` values can hold
real image refs and never inherit documentation status from that property
name. Nested collections under those keywords inherit the same exclusion, so
a ``description`` key inside a ``default`` object cannot re-enter docs.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

DOCUMENTATION_FIELD_KEYS = frozenset({"description", "example", "examples"})

# Schema keywords that can hold real image-shaped values and must not
# inherit documentation status from an ancestor key named description/example.
SCHEMA_VALUE_KEYS = frozenset({"default", "enum", "const"})


@dataclass(frozen=True, slots=True)
class _AnchorChain:
    """Immutable cons cell: this frame's own anchor plus the parent chain.

    Pushing a frame is O(1); walking ``names()`` is O(depth). Anchor sets
    are materialized only when recording pending lines or alias edges.
    """

    name: str | None
    parent: _AnchorChain | None = None

    def names(self) -> Iterator[str]:
        node: _AnchorChain | None = self
        while node is not None:
            if node.name is not None:
                yield node.name
            node = node.parent


@dataclass
class _Frame:
    """One currently-open YAML mapping or sequence.

    ``anchors`` is a parent-linked chain of this collection's own anchor
    (if any) plus every anchor already open above it.

    ``expect_key``/``key_is_doc``/``key_is_schema_value`` only apply to
    ``kind == "map"``: they alternate key/value parsing and remember whether
    the key just consumed was a documentation key (upcoming value inherits
    docs status) or a schema-value keyword (upcoming value must *not*
    inherit docs status, even under a docs ancestor).

    ``in_schema_value`` is inherited by nested collections created while
    processing a ``default``/``enum``/``const`` value. It overrides
    ``key_is_doc`` so a nested ``description`` key cannot re-enter docs.
    """

    kind: Literal["map", "seq"]
    in_docs: bool
    anchors: _AnchorChain
    expect_key: bool = False
    key_is_doc: bool = False
    key_is_schema_value: bool = False
    in_schema_value: bool = False


@dataclass
class _PendingLines:
    line_range: range
    owning_anchors: frozenset[str]


def _event_line_range(event: yaml.Event) -> range:
    """Inclusive 1-based line range covered by a YAML parse event.

    When ``end_mark.column == 0``, the mark points at the next token / EOF
    line and that line is excluded.
    """
    start = event.start_mark.line + 1
    end = event.end_mark.line if event.end_mark.column == 0 else event.end_mark.line + 1
    if end < start:
        end = start
    return range(start, end + 1)


def _expand_tainted(aliased_outside_docs: set[str], refs_from: dict[str, set[str]]) -> set[str]:
    """BFS: outside-docs aliases taint every anchor they reach via in-docs edges."""
    tainted = set(aliased_outside_docs)
    queue: deque[str] = deque(aliased_outside_docs)
    while queue:
        container = queue.popleft()
        for referenced in refs_from.get(container, ()):
            if referenced not in tainted:
                tainted.add(referenced)
                queue.append(referenced)
    return tainted


def documentation_field_lines(yaml_text: str) -> set[int]:
    """Return 1-based line numbers of scalars under documentation keys.

    Covers ``description``, ``example``, and ``examples``, including all
    descendant scalars in those subtrees (nested mappings and sequences),
    except values of schema keywords ``default`` / ``enum`` / ``const`` —
    those never inherit documentation status (a CRD property named
    ``description`` must not launder its own defaults). Multi-document
    streams are fully scanned; anchor taint is scoped per document. On
    parse failure, returns an empty set so callers fall back to the
    existing line-scan behavior without documentation downgrades.

    A scalar's anchor definition is excluded from the result if that same
    anchor is ever referenced (by alias or merge key) from outside a
    documentation field — directly, or transitively via other docs-anchored
    structures that are themselves referenced outside docs. See the module
    docstring for why.
    """
    if not any(key in yaml_text for key in DOCUMENTATION_FIELD_KEYS):
        return set()

    lines: set[int] = set()
    pending: list[_PendingLines] = []
    aliased_outside_docs: set[str] = set()
    # container_anchor → anchors referenced by alias while inside it (in docs)
    refs_from: dict[str, set[str]] = defaultdict(set)
    stack: list[_Frame] = []

    def effective_in_docs() -> bool:
        if not stack:
            return False
        frame = stack[-1]
        # Inherited schema-value taint wins over a nested docs key.
        if frame.in_schema_value or (
            frame.kind == "map" and not frame.expect_key and frame.key_is_schema_value
        ):
            return False
        if frame.kind == "seq":
            return frame.in_docs
        if frame.expect_key:
            return frame.in_docs
        return frame.in_docs or frame.key_is_doc

    def entering_schema_value() -> bool:
        """True when the next nested collection is under a schema-value key
        or already inside an inherited schema-value subtree."""
        if not stack:
            return False
        frame = stack[-1]
        if frame.in_schema_value:
            return True
        return frame.kind == "map" and not frame.expect_key and frame.key_is_schema_value

    def current_chain() -> _AnchorChain | None:
        return stack[-1].anchors if stack else None

    def advance(*, is_doc_key: bool, is_schema_value_key: bool) -> None:
        """Record that the innermost mapping just consumed one key or value
        (a scalar/alias, or a nested collection that just closed)."""
        if not stack or stack[-1].kind != "map":
            return
        frame = stack[-1]
        if frame.expect_key:
            frame.expect_key = False
            frame.key_is_doc = is_doc_key
            frame.key_is_schema_value = is_schema_value_key
        else:
            frame.expect_key = True
            frame.key_is_doc = False
            frame.key_is_schema_value = False

    def finalize_document() -> None:
        """Apply per-document taint closure, then clear anchor namespace."""
        nonlocal pending, aliased_outside_docs, refs_from
        tainted = _expand_tainted(aliased_outside_docs, refs_from)
        for item in pending:
            if item.owning_anchors & tainted:
                continue
            lines.update(item.line_range)
        pending = []
        aliased_outside_docs = set()
        refs_from = defaultdict(set)

    try:
        for event in yaml.parse(yaml_text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.DocumentEndEvent):
                finalize_document()
                continue
            if isinstance(event, yaml.MappingStartEvent | yaml.SequenceStartEvent):
                stack.append(
                    _Frame(
                        kind="map" if isinstance(event, yaml.MappingStartEvent) else "seq",
                        in_docs=effective_in_docs(),
                        anchors=_AnchorChain(event.anchor, current_chain()),
                        expect_key=isinstance(event, yaml.MappingStartEvent),
                        in_schema_value=entering_schema_value(),
                    )
                )
            elif isinstance(event, yaml.MappingEndEvent | yaml.SequenceEndEvent):
                if stack:
                    stack.pop()
                advance(is_doc_key=False, is_schema_value_key=False)
            elif isinstance(event, yaml.ScalarEvent | yaml.AliasEvent):
                in_docs = effective_in_docs()
                is_key = bool(stack) and stack[-1].kind == "map" and stack[-1].expect_key
                chain = current_chain()
                if isinstance(event, yaml.AliasEvent):
                    if not in_docs:
                        aliased_outside_docs.add(event.anchor)
                    elif chain is not None:
                        for container in chain.names():
                            refs_from[container].add(event.anchor)
                elif in_docs and not is_key:
                    # Only values contribute: a key named ``default`` under a
                    # property named ``description`` must not mark its line.
                    owning = set(chain.names()) if chain is not None else set()
                    if event.anchor:
                        owning.add(event.anchor)
                    pending.append(_PendingLines(_event_line_range(event), frozenset(owning)))
                is_doc_key = (
                    is_key
                    and isinstance(event, yaml.ScalarEvent)
                    and event.value in DOCUMENTATION_FIELD_KEYS
                )
                is_schema_value_key = (
                    is_key
                    and isinstance(event, yaml.ScalarEvent)
                    and event.value in SCHEMA_VALUE_KEYS
                )
                advance(is_doc_key=is_doc_key, is_schema_value_key=is_schema_value_key)
    except (yaml.YAMLError, RecursionError):
        return set()

    # Stream may end without a final DocumentEnd in some edge cases.
    finalize_document()
    return lines
