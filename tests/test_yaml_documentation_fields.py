"""Direct unit tests for rules/yaml_documentation_fields.py.

Asserts on the exact line sets ``documentation_field_lines()`` returns,
rather than only on downstream severity through `scan_file()` — a state
machine this shape should be verifiable without driving the whole rule.
"""

import time

from rules.yaml_documentation_fields import documentation_field_lines


class TestBasicShapes:
    def test_no_documentation_keys_returns_empty_set(self):
        assert documentation_field_lines("image: quay.io/org/img:v1\n") == set()

    def test_flow_scalar_description_marks_its_line(self):
        text = 'description: "See quay.io/org/doc:v1"\n'
        assert documentation_field_lines(text) == {1}

    def test_block_scalar_description_marks_key_and_every_body_line(self):
        text = "description: |-\n  line one quay.io/org/a:v1\n  line two quay.io/org/b:v1\n"
        # The scalar event's start mark is the `description: |-` indicator
        # line itself, so it's included alongside the body lines.
        assert documentation_field_lines(text) == {1, 2, 3}

    def test_nested_example_object_marks_descendant_lines(self):
        text = "example:\n  image: ghcr.io/org/nested:latest\n"
        assert documentation_field_lines(text) == {2}

    def test_sibling_key_outside_docs_not_marked(self):
        text = "properties:\n  image:\n    description: |-\n      docs only\n    default: real\n"
        # Lines 3-4 (the `description: |-` indicator plus its body) are
        # marked; line 5 (`default:`) is a sibling of description, not a
        # descendant, so it's excluded.
        assert documentation_field_lines(text) == {3, 4}

    def test_property_named_description_default_not_marked(self):
        """A CRD/API property literally named ``description`` is not prose —
        its schema ``default``/``enum``/``const`` values must stay unmarked."""
        text = (
            "properties:\n"
            "  description:\n"
            "    default: quay.io/org/should-be-blocker:v1\n"
            "    enum: [quay.io/org/enum-a:v1]\n"
            "    const: quay.io/org/const-a:v1\n"
        )
        assert documentation_field_lines(text) == set()

    def test_nested_docs_key_under_schema_value_not_marked(self):
        """Schema-value taint propagates into nested collections: a
        ``description`` key under ``default`` must not re-enter docs."""
        text = (
            "properties:\n"
            "  description:\n"
            "    default:\n"
            "      description: quay.io/org/nested-under-default:v1\n"
            "      example: quay.io/org/nested-under-default-ex:v1\n"
        )
        assert documentation_field_lines(text) == set()

    def test_multi_document_stream_scans_both_documents(self):
        text = "description: quay.io/org/a:v1\n---\ndescription: quay.io/org/b:v1\n"
        assert documentation_field_lines(text) == {1, 3}

    def test_cross_document_anchor_name_collision_does_not_taint(self):
        """YAML anchors are per-document; an outside-docs alias in doc A must
        not unmark a docs-only definition that reuses the same name in doc B."""
        text = (
            "real: &img registry.io/prod-real:v1\n"
            "usage: *img\n"
            "---\n"
            "description: &img ghcr.io/org/doc-example:v1\n"
        )
        assert documentation_field_lines(text) == {4}

    def test_invalid_yaml_returns_empty_set(self):
        text = "description: |-\n  docs\nimage: real\n  bad-indent: true\n"
        assert documentation_field_lines(text) == set()

    def test_flow_style_same_line_key_shares_lines_with_docs_key(self):
        """Known, accepted limitation: line-granular tracking can't
        distinguish a real key from a doc key sharing the same physical
        line in flow-style YAML."""
        text = '{description: "doc text", image: "real value"}\n'
        assert documentation_field_lines(text) == {1}


class TestAnchorAliasSafety:
    def test_alias_under_docs_does_not_mark_the_alias_line(self):
        text = "image: &pin quay.io/org/real:v1.0\ndescription: *pin\n"
        assert documentation_field_lines(text) == set()

    def test_alias_referenced_before_anchor_defined_marks_nothing(self):
        text = "description: *pin\nimage: &pin quay.io/org/real:v1.0\n"
        assert documentation_field_lines(text) == set()

    def test_anchor_in_docs_aliased_outside_docs_is_excluded(self):
        """Definition line stays unmarked when the only image text would
        otherwise hide behind a docs downgrade at a real alias site."""
        text = "description: &img quay.io/org/real:v1\ncontainers:\n  - image: *img\n"
        assert documentation_field_lines(text) == set()

    def test_anchor_in_docs_merged_outside_docs_is_excluded(self):
        text = (
            "example: &pod\n"
            "  image: quay.io/org/real:v1\n"
            "spec:\n"
            "  containers:\n"
            "    - name: main\n"
            "      <<: *pod\n"
        )
        assert documentation_field_lines(text) == set()

    def test_anchor_in_docs_aliased_only_within_docs_stays_marked(self):
        """Docs-only alias chains stay marked when nothing references them
        outside documentation fields."""
        text = "description: &img ghcr.io/org/sample:v1\nexample: *img\n"
        assert documentation_field_lines(text) == {1}

    def test_transitive_docs_alias_merged_outside_docs_is_excluded(self):
        """Image anchored in docs, referenced under a second docs structure,
        that structure merged at a real site — definition line unmarked."""
        text = (
            "description: &img quay.io/org/real:v1.2.3\n"
            "example: &pod\n"
            "  image: *img\n"
            "containers:\n"
            "  - name: main\n"
            "    <<: *pod\n"
        )
        assert documentation_field_lines(text) == set()

    def test_transitive_docs_alias_sequence_item_outside_docs_is_excluded(self):
        text = (
            "description: &img quay.io/org/real:v1.2.3\n"
            "example: &pod\n"
            "  image: *img\n"
            "containers:\n"
            "  - *pod\n"
        )
        assert documentation_field_lines(text) == set()

    def test_three_hop_docs_alias_chain_merged_outside_is_excluded(self):
        text = (
            "description: &img quay.io/org/real:v1\n"
            "example: &a\n"
            "  image: *img\n"
            "examples: &b\n"
            "  <<: *a\n"
            "containers:\n"
            "  - <<: *b\n"
        )
        assert documentation_field_lines(text) == set()

    def test_transitive_docs_only_chain_stays_marked(self):
        """Docs-only multi-hop alias chains stay marked."""
        text = (
            "description: &img ghcr.io/org/sample:v1\n"
            "example: &pod\n"
            "  image: *img\n"
            "examples:\n"
            "  - *pod\n"
        )
        assert documentation_field_lines(text) == {1}

    def test_anchor_reuse_stays_linear_in_alias_count(self):
        """Doubling alias chains must stay near-linear in alias count."""
        lines = ["a0: &a0 quay.io/org/pinned:v1"]
        for i in range(1, 30):
            lines.append(f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]")
        lines.append("description: *a29")
        text = "\n".join(lines) + "\n"
        start = time.monotonic()
        result = documentation_field_lines(text)
        elapsed = time.monotonic() - start
        assert result == set()
        assert elapsed < 5, f"documentation_field_lines() took {elapsed:.2f}s, expected < 5s"


class TestDeepNesting:
    def test_deeply_nested_sequence_does_not_raise(self):
        depth = 1100
        nested = "[" * depth + "1" + "]" * depth
        text = f"description: {nested}\n"
        # Must not raise RecursionError; the whole flow sequence is inline
        # on line 1, so that's the only line there is to mark.
        assert documentation_field_lines(text) == {1}

    def test_deeply_nested_sequence_outside_docs_is_unaffected(self):
        depth = 1100
        nested = "[" * depth + "1" + "]" * depth
        text = f"description: {nested}\nimage: quay.io/org/real:v1\n"
        # Must not raise RecursionError, and the unrelated `image:` line
        # (not itself under `description`) must never be a candidate.
        assert 2 not in documentation_field_lines(text)

    def test_nested_unique_anchors_stay_near_linear(self):
        """Deep nesting with a unique anchor per level stays near-linear.

        Compact flow nesting keeps file size O(depth) so the budget measures
        bookkeeping, not indent-driven I/O.
        """
        depth = 4000
        inner = "v: docs-only"
        for i in range(depth - 1, -1, -1):
            inner = f"k{i}: &a{i} {{{inner}}}"
        text = f"description: {{{inner}}}\n"
        start = time.monotonic()
        result = documentation_field_lines(text)
        elapsed = time.monotonic() - start
        assert result  # deepest scalar under docs is marked
        assert elapsed < 2, (
            f"documentation_field_lines() took {elapsed:.2f}s on {depth} nested "
            f"anchors ({len(text)} bytes); expected < 2s (near-linear)"
        )
