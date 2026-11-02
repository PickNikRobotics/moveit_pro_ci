#!/usr/bin/env python3
"""Structure-aware review diff for MoveIt Pro Behavior Tree XML.

GitHub's line diff shows a block that gained a wrapper node as a full delete and re-add. This tool
matches nodes between the base and head versions with xmldiff, then reports only what changed:
added and removed nodes, nodes moved to a different parent, reordered children, and attribute or
text edits. A node wrapped in (or unwrapped from) new control or decorator nodes is not a move.

It prints GitHub workflow-command annotations to stdout and writes a Markdown report.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import quote

from lxml import etree
from xmldiff.diff import Differ

# GitHub shows at most 10 annotations of one type per step; the rest go only to the report.
MAX_ANNOTATIONS = 10
# Matching is quadratic in node count. Real Objectives have under 100 nodes.
MAX_NODES = 1500
# A leaf that changed and also moved to another tree definition must be this similar to match.
MOVED_LEAF_RATIO = 0.9
BT_SECTIONS = ("BehaviorTree", "TreeNodesModel")


@dataclass(frozen=True)
class Change:
    kind: str  # added, removed, moved, changed, reordered, error
    message: str
    line: int | None  # line in the head file to annotate, if any


class BehaviorTreeDiffer(Differ):
    """Pairs nodes only when they are the same Behavior, so a rewrite reads as remove and add."""

    def __init__(self):
        super().__init__(best_match=True)
        self._pins: dict[int, etree._Element] = {}

    def set_trees(self, left, right):
        super().set_trees(left, right)
        # Pair leaves first with an order-preserving alignment, as a line diff would, so look-alike
        # siblings cannot trade places. Leaves that moved out of order fall through to best_match.
        # The node lists keep the lxml proxies alive, which keeps their id() keys valid.
        self._nodes = [list(tree.iter(tag=etree.Element)) for tree in (self.left, self.right)]
        self._ancestries = {id(n): _ancestry(n) for nodes in self._nodes for n in nodes}
        lefts, rights = ([n for n in nodes if not len(n)] for nodes in self._nodes)
        self._pins = {}
        for left_leaf, right_leaf in self._align(lefts, rights):
            self._pins[id(left_leaf)], self._pins[id(right_leaf)] = right_leaf, left_leaf

    def _align(self, lefts, rights):
        """Order-preserving pairs of same-identity leaves: most exact pairs, then highest similarity."""
        exact_bonus = len(lefts) + 1  # one exact pair outweighs any number of near pairs
        similarity = {}
        for i, left in enumerate(lefts):
            for j, right in enumerate(rights):
                if _identity(left) == _identity(right):
                    ratio = self._leaf_similarity(left, right)
                    if ratio >= self.F:
                        exact = self.node_text(left) == self.node_text(right)
                        similarity[i, j] = ratio + (exact_bonus if exact else 0)
        # best[i][j]: highest total score aligning lefts[i:] with rights[j:].
        best = [[0.0] * (len(rights) + 1) for _ in range(len(lefts) + 1)]
        for i in range(len(lefts) - 1, -1, -1):
            for j in range(len(rights) - 1, -1, -1):
                best[i][j] = max(best[i + 1][j], best[i][j + 1])
                if (i, j) in similarity:
                    best[i][j] = max(best[i][j], similarity[i, j] + best[i + 1][j + 1])
        pairs, i, j = [], 0, 0
        while i < len(lefts) and j < len(rights):
            if (i, j) in similarity and best[i][j] == similarity[i, j] + best[i + 1][j + 1]:
                pairs.append((lefts[i], rights[j]))
                i, j = i + 1, j + 1
            elif best[i][j] == best[i + 1][j]:
                i += 1
            else:
                j += 1
        return pairs

    def _leaf_similarity(self, left, right):
        ratio = self.leaf_ratio(left, right)
        # The last two ancestors are the BehaviorTree (or TreeNodesModel) and root.
        if ratio < MOVED_LEAF_RATIO and self._ancestries[id(left)][-2:] != self._ancestries[id(right)][-2:]:
            return 0
        return ratio

    def child_ratio(self, left, right):
        if not len(left) and not len(right):
            return None
        left_kept = list(kept_children(left, lambda n: id(n) in self._l2rmap))
        right_kept = {id(n) for n in kept_children(right, lambda n: id(n) in self._r2lmap)}
        shared = sum(1 for n in left_kept if id(self._l2rmap[id(n)]) in right_kept)
        return shared / max(len(left_kept), len(right_kept), 1)

    def node_ratio(self, left, right):
        if id(left) in self._pins or id(right) in self._pins:
            return 1.0 if self._pins.get(id(left)) is right else 0
        if _identity(left) != _identity(right):
            return 0
        # Tree and model definitions have file-unique IDs.
        parent = left.getparent()
        if left.tag == "BehaviorTree" or (parent is not None and parent.tag == "TreeNodesModel"):
            return 1.0
        # A parent whose children all differ is a different node, even with the same tag and ID.
        if len(left) and len(right) and self.child_ratio(left, right) == 0:
            return 0
        if not len(left) and not len(right) and not self._leaf_similarity(left, right):
            return 0
        # Prefer the candidate in the same place in the tree when several look alike.
        ratio = super().node_ratio(left, right)
        place = SequenceMatcher(None, self._ancestries[id(left)], self._ancestries[id(right)]).ratio()
        return 0.8 * ratio + 0.2 * place


def kept_children(node: etree._Element, is_matched) -> list[etree._Element]:
    """Matched children of `node`, looking through unmatched wrapper nodes."""
    result = []
    for child in node:
        result.extend([child] if is_matched(child) else kept_children(child, is_matched))
    return result


def _identity(node: etree._Element) -> tuple:
    """A Behavior is identified by its ID, and an ID-less node such as a port by its name."""
    return node.tag, node.get("ID"), None if "ID" in node.attrib else node.get("name")


def _ancestry(node: etree._Element) -> list[tuple]:
    return [(n.tag, n.get("ID"), n.get("name")) for n in node.iterancestors()]


def _parse(xml: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_comments=True,
        remove_pis=True,
    )
    tree = etree.fromstring(xml, parser).getroottree()
    if tree.docinfo.doctype:
        raise ValueError("DOCTYPE declarations are not supported")
    return tree.getroot()


def is_behavior_tree(xml: bytes) -> bool:
    try:
        root = _parse(xml)
    except (etree.XMLSyntaxError, ValueError):
        return False
    return root.tag == "root" and any(child.tag in BT_SECTIONS for child in root)


def _code(text: str) -> str:
    """Markdown code span that the text cannot break out of."""
    fence = "`" * (max((len(run) for run in re.findall("`+", text)), default=0) + 1)
    return f"{fence} {text} {fence}" if fence != "`" else f"`{text}`"


def label(node: etree._Element) -> str:
    parts = [str(node.tag)]
    for key in ("ID", "name"):
        if key in node.attrib:
            parts.append(f'{key}="{node.attrib[key]}"')
    return _code(" ".join(parts))


def _value(value: str) -> str:
    return _code(value) if value else "(empty)"


def _text(node: etree._Element) -> str:
    return " ".join((node.text or "").split())


def _start_line(head_lines: list[str], node: etree._Element) -> int:
    """First line of the start tag. lxml's sourceline is where a multi-line start tag ends."""
    opening = f"<{node.tag}"
    for number in range(node.sourceline, 0, -1):
        if opening in head_lines[number - 1]:
            return number
    return node.sourceline


def _attribute_line(head_lines: list[str], node: etree._Element, attribute: str) -> int:
    pattern = re.compile(rf"(^|\s){re.escape(attribute)}\s*=")
    for number in range(_start_line(head_lines, node), node.sourceline + 1):
        if pattern.search(head_lines[number - 1]):
            return number
    return _start_line(head_lines, node)


def diff_behavior_tree(before: bytes, after: bytes) -> list[Change]:
    left_root, right_root = _parse(before), _parse(after)
    for root in (left_root, right_root):
        count = sum(1 for _ in root.iter(tag=etree.Element))
        if count > MAX_NODES:
            raise ValueError(f"{count} nodes is over the {MAX_NODES}-node limit")
    differ = BehaviorTreeDiffer()
    differ.set_trees(left_root, right_root)
    # Differ works on a deep copy of the left tree; match pairs refer to that copy.
    l2r: dict[etree._Element, etree._Element] = {}
    r2l: dict[etree._Element, etree._Element] = {}
    for left, right, _ in differ.match():
        l2r[left] = right
        r2l[right] = left
    left_root = differ.left
    # split("\n") keeps line numbers aligned with libxml2, which splitlines() does not.
    base_lines = _decode(before, left_root).split("\n")
    head_lines = _decode(after, right_root).split("\n")

    def matched_parent(node: etree._Element, matched: dict) -> etree._Element | None:
        """Nearest ancestor that exists on both sides, skipping added or removed wrappers."""
        parent = node.getparent()
        while parent is not None and parent not in matched:
            parent = parent.getparent()
        return parent

    def matched_children(node: etree._Element, matched: dict) -> list[etree._Element]:
        return kept_children(node, matched.__contains__)

    def region(node: etree._Element, matched: dict, verb: str) -> str:
        """Describe the unmatched nodes below `node` that it adds or removes with it."""
        count = sum(
            1
            for n in node.iterdescendants(tag=etree.Element)
            if n not in matched and matched_parent(n, matched) is matched_parent(node, matched)
        )
        return f" with {count} more {verb} node{'s' if count != 1 else ''}" if count else ""

    changes: list[Change] = []
    for right in right_root.iter(tag=etree.Element):
        left = r2l.get(right)
        if left is None:
            # Report each added subtree once, at its top node.
            if right.getparent() in r2l:
                kept = matched_children(right, r2l)
                note = f", wraps existing {', '.join(label(n) for n in kept)}" if kept else ""
                changes.append(
                    Change(
                        "added",
                        f"Added {label(right)}{region(right, r2l, 'new')}{note}",
                        _start_line(head_lines, right),
                    )
                )
            continue

        if right is not right_root:
            old_parent = matched_parent(left, l2r)
            new_parent = matched_parent(right, r2l)
            if old_parent is not None and l2r[old_parent] is not new_parent:
                into = f"under {label(new_parent)} (line {_start_line(head_lines, new_parent)})"
                wrapper = right.getparent()
                if wrapper is new_parent:
                    into = f"to {into}"
                else:
                    into = f"into new {label(wrapper)} (line {_start_line(head_lines, wrapper)}) {into}"
                message = (
                    f"Moved {label(right)} from under {label(old_parent)} (base line "
                    f"{_start_line(base_lines, old_parent)}) {into}"
                )
                changes.append(Change("moved", message, _start_line(head_lines, right)))

        for name in sorted(set(left.attrib) | set(right.attrib)):
            old, new = left.attrib.get(name), right.attrib.get(name)
            if old == new:
                continue
            if new is None:
                detail, line = f"removed `{name}` (was {_value(old)})", _start_line(head_lines, right)
            else:
                was = "added" if old is None else f"{_value(old)} →"
                detail, line = f"`{name}`: {was} {_value(new)}", _attribute_line(head_lines, right, name)
            changes.append(Change("changed", f"Changed {label(right)} {detail}", line))

        if _text(left) != _text(right):
            changes.append(Change("changed", f"Changed {label(right)} text", _start_line(head_lines, right)))

        kept_right = matched_children(right, r2l)
        kept_left = [l2r[n] for n in matched_children(left, l2r)]
        common = set(kept_right) & set(kept_left)
        if [n for n in kept_left if n in common] != [n for n in kept_right if n in common]:
            changes.append(
                Change("reordered", f"Reordered children of {label(right)}", _start_line(head_lines, right))
            )

    for left in left_root.iter(tag=etree.Element):
        if left not in l2r and left.getparent() in l2r:
            anchor = l2r[left.getparent()]
            kept = matched_children(left, l2r)
            note = f", unwraps existing {', '.join(label(l2r[n]) for n in kept)}" if kept else ""
            message = f"Removed {label(left)}{region(left, l2r, 'removed')} from {label(anchor)}{note}"
            changes.append(Change("removed", message, _start_line(head_lines, anchor)))
    return changes


def _decode(xml: bytes, root: etree._Element) -> str:
    return xml.decode(root.getroottree().docinfo.encoding or "utf-8", errors="replace")


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def annotation(path: str, change: Change) -> str:
    title = _escape_property(f"Behavior Tree: {change.kind}")
    return f"::notice file={_escape_property(path)},line={change.line},title={title}::{_escape_data(change.message)}"


def render_report(results: dict[str, list[Change]], file_url: str | None, whitespace_url: str | None) -> str:
    lines = ["## Behavior Tree review diff", ""]
    if whitespace_url:
        lines += [f"Line diff with whitespace hidden: [Files changed]({whitespace_url})", ""]
    if not results:
        lines.append("No modified Behavior Tree XML files.")
    for path, changes in results.items():
        lines += [f"### {_code(path)}", ""]
        if not changes:
            lines.append("No structural changes. Only formatting or comments differ.")
        for change in changes:
            where = ""
            if change.line and file_url:
                where = f" ([L{change.line}]({file_url}/{quote(path)}#L{change.line}))"
            lines.append(f"- {change.message}{where}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def changed_xml_files(base: str, head: str) -> Iterable[tuple[str, str]]:
    """(base path, head path) for each XML file modified or renamed between the commits."""
    out = os.fsdecode(_git("diff", "--name-status", "-M", "-z", base, head, "--", "*.xml"))
    fields = out.split("\0")
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        if status.startswith("R"):
            yield fields[index + 1], fields[index + 2]
            index += 3
        else:
            if status == "M":
                yield fields[index + 1], fields[index + 1]
            index += 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="base commit")
    parser.add_argument("--head", required=True, help="head commit")
    parser.add_argument("--report", help="append the Markdown report to this file")
    parser.add_argument("--file-url", help="URL prefix for head file links, ending in the head commit")
    parser.add_argument("--whitespace-url", help="link to the PR's Files changed view with whitespace hidden")
    args = parser.parse_args(argv)

    results: dict[str, list[Change]] = {}
    emitted = 0
    for base_path, head_path in changed_xml_files(args.base, args.head):
        before = _git("show", f"{args.base}:{base_path}")
        after = _git("show", f"{args.head}:{head_path}")
        # A Behavior Tree that no longer parses still gets a warning from diff_behavior_tree.
        if not (is_behavior_tree(before) or is_behavior_tree(after)):
            continue
        try:
            changes = diff_behavior_tree(before, after)
        except Exception as error:  # noqa: BLE001 - one bad file must not hide the others
            print(
                f"::warning file={_escape_property(head_path)},title=Behavior Tree review diff::"
                f"{_escape_data(f'Could not diff this file: {error}')}"
            )
            changes = [Change("error", f"Could not diff this file: {error}", None)]
        results[head_path] = changes
        for change in changes:
            if change.line and emitted < MAX_ANNOTATIONS:
                print(annotation(head_path, change))
                emitted += 1

    report = render_report(results, args.file_url, args.whitespace_url)
    if args.report:
        with open(args.report, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        sys.stdout.write(report)
    total = sum(len(c) for c in results.values())
    if total > emitted:
        print(f"{total - emitted} of {total} changes are listed only in the job summary.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
