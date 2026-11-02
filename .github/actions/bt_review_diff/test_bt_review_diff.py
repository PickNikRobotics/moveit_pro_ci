import subprocess
from collections import Counter
from pathlib import Path

import pytest

import bt_review_diff as btd

BEFORE = b"""\
<root BTCPP_format="4">
  <BehaviorTree ID="Pick">
    <Control ID="Sequence">
      <Action ID="LogMessage" message="start" />
      <Control ID="Sequence" name="Work">
        <Action ID="MoveToWaypoint" waypoint_name="home" />
        <Action ID="Script" code="x := 1" />
      </Control>
    </Control>
  </BehaviorTree>
</root>
"""

# The "Work" block wrapped one level deeper, reformatted as prettier would.
WRAPPED = b"""\
<root BTCPP_format="4">
  <BehaviorTree ID="Pick">
    <Control ID="Sequence">
      <Action ID="LogMessage" message="start" />
      <Decorator ID="RetryUntilSuccessful" num_attempts="3">
        <Control ID="Sequence" name="Work">
          <Action ID="MoveToWaypoint" waypoint_name="home" />
          <Action ID="Script" code="x := 1" />
        </Control>
      </Decorator>
    </Control>
  </BehaviorTree>
</root>
"""


def kinds(changes):
    return [(c.kind, c.message) for c in changes]


def test_wrapping_a_block_reports_only_the_wrapper():
    changes = btd.diff_behavior_tree(BEFORE, WRAPPED)
    assert kinds(changes) == [
        (
            "added",
            'Added `Decorator ID="RetryUntilSuccessful"`, wraps existing `Control ID="Sequence" name="Work"`',
        )
    ]
    assert changes[0].line == 5


def test_unwrapping_a_block_reports_only_the_removed_wrapper():
    changes = btd.diff_behavior_tree(WRAPPED, BEFORE)
    assert kinds(changes) == [
        (
            "removed",
            (
                'Removed `Decorator ID="RetryUntilSuccessful"` from `Control ID="Sequence"`, '
                'unwraps existing `Control ID="Sequence" name="Work"`'
            ),
        )
    ]


def test_edit_inside_a_wrapped_block_points_at_the_attribute_line():
    after = WRAPPED.replace(
        b'<Action ID="MoveToWaypoint" waypoint_name="home" />',
        b'<Action\n            ID="MoveToWaypoint"\n            waypoint_name="pick"\n          />',
    )
    changes = [c for c in btd.diff_behavior_tree(BEFORE, after) if c.kind == "changed"]
    assert kinds(changes) == [
        ("changed", 'Changed `Action ID="MoveToWaypoint"` `waypoint_name`: `home` → `pick`')
    ]
    assert after.decode().splitlines()[changes[0].line - 1].strip() == 'waypoint_name="pick"'


def test_added_subtree_is_one_line():
    after = BEFORE.replace(
        b'<Action ID="LogMessage" message="start" />',
        b'<Action ID="LogMessage" message="start" />'
        b'<Control ID="Fallback"><Action ID="A" /><Action ID="B" /></Control>',
    )
    assert kinds(btd.diff_behavior_tree(BEFORE, after)) == [
        ("added", 'Added `Control ID="Fallback"` with 2 more new nodes')
    ]


def test_replacing_a_behavior_is_a_remove_and_add_not_an_edit():
    after = BEFORE.replace(b'ID="Script" code="x := 1"', b'ID="LogMessage" message="x"')
    assert sorted(c.kind for c in btd.diff_behavior_tree(BEFORE, after)) == ["added", "removed"]


def test_moving_a_node_to_another_parent_is_a_move():
    after = BEFORE.replace(b'<Action ID="Script" code="x := 1" />\n', b"").replace(
        b"    </Control>\n  </BehaviorTree>",
        b'    <Action ID="Script" code="x := 1" />\n    </Control>\n  </BehaviorTree>',
    )
    assert kinds(btd.diff_behavior_tree(BEFORE, after)) == [
        (
            "moved",
            (
                'Moved `Action ID="Script"` from under `Control ID="Sequence" name="Work"` (base line 5) '
                'to under `Control ID="Sequence"` (line 3)'
            ),
        )
    ]


def test_reordering_children_is_reported():
    after = BEFORE.replace(
        b'<Action ID="MoveToWaypoint" waypoint_name="home" />\n        <Action ID="Script" code="x := 1" />',
        b'<Action ID="Script" code="x := 1" />\n        <Action ID="MoveToWaypoint" waypoint_name="home" />',
    )
    assert kinds(btd.diff_behavior_tree(BEFORE, after)) == [
        ("reordered", 'Reordered children of `Control ID="Sequence" name="Work"`')
    ]


def test_formatting_and_comments_only_is_no_change():
    after = BEFORE.replace(
        b'<Action ID="LogMessage"', b'<!-- note -->\n      <Action\n        ID="LogMessage"'
    )
    assert btd.diff_behavior_tree(BEFORE, after) == []


def test_doctype_is_rejected():
    with pytest.raises(ValueError, match="DOCTYPE"):
        btd.diff_behavior_tree(
            BEFORE, b'<!DOCTYPE root [<!ENTITY x SYSTEM "file:///etc/hostname">]><root>&x;</root>'
        )


def test_annotation_escapes_workflow_command_syntax():
    change = btd.Change("changed", "50% done\nnext", 3)
    assert btd.annotation("a,b:c.xml", change) == (
        "::notice file=a%2Cb%3Ac.xml,line=3,title=Behavior Tree%3A changed::50%25 done%0Anext"
    )


def test_wrapping_one_of_two_look_alike_blocks_does_not_cross_them():
    block = b'<Control ID="Sequence"><Action ID="Move" to="mid" /><Action ID="Grip" p="1" /></Control>'
    before = (
        b'<root><BehaviorTree ID="T"><Control ID="Sequence">'
        + block
        + block
        + b"</Control></BehaviorTree></root>"
    )
    after = before.replace(block, b'<Decorator ID="Retry">' + block + b"</Decorator>", 1)
    assert [c.kind for c in btd.diff_behavior_tree(before, after)] == ["added"]


def test_unwrapping_edited_look_alike_siblings_keeps_their_order():
    # Same Behavior three times, two with the same waypoint, all edited alike while unwrapped.
    moves = [b'<SubTree ID="Move" waypoint="%s" />' % w for w in (b"a", b"b", b"a")]
    wrapped = b"".join(b'<Decorator ID="Retry">' + m + b"</Decorator>" for m in moves)
    edited = b"".join(m.replace(b" />", b' speed="1" />') for m in moves)
    tree = b'<root><BehaviorTree ID="T"><Control ID="Sequence">%s</Control></BehaviorTree></root>'
    kinds = Counter(c.kind for c in btd.diff_behavior_tree(tree % wrapped, tree % edited))
    assert kinds == {"removed": 3, "changed": 3}


def test_deleting_a_nested_block_is_one_removal():
    # A removed Sequence must not take the place of the surviving outer Sequence.
    before = BEFORE.replace(
        b'<Action ID="LogMessage" message="start" />',
        b'<Action ID="LogMessage" message="start" />\n'
        b'<Control ID="Sequence"><Action ID="A" /><Action ID="B" /><Action ID="C" /></Control>',
    )
    assert kinds(btd.diff_behavior_tree(before, BEFORE)) == [
        ("removed", 'Removed `Control ID="Sequence"` with 3 more removed nodes from `Control ID="Sequence"`')
    ]


def test_wrapping_the_only_child_of_a_tree_reports_only_the_wrapper():
    before = (
        b'<root><BehaviorTree ID="T"><Control ID="Sequence"><Action ID="A" /></Control></BehaviorTree></root>'
    )
    after = before.replace(
        b'<Control ID="Sequence">', b'<Decorator ID="ForceSuccess"><Control ID="Sequence">'
    )
    after = after.replace(b"</Control>", b"</Control></Decorator>")
    assert [c.kind for c in btd.diff_behavior_tree(before, after)] == ["added"]


def test_rewriting_a_whole_tree_keeps_the_tree_definition():
    before = b'<root><BehaviorTree ID="T"><Action ID="A" /></BehaviorTree></root>'
    after = b'<root><BehaviorTree ID="T"><Action ID="B" /></BehaviorTree></root>'
    assert [c.message for c in btd.diff_behavior_tree(before, after)] == [
        'Added `Action ID="B"`',
        'Removed `Action ID="A"` from `BehaviorTree ID="T"`',
    ]


def test_lines_stay_aligned_in_a_latin1_file():
    before = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<root><BehaviorTree ID="é">\n<Action ID="A" x="1" />\n</BehaviorTree></root>'
    after = before.replace('x="1"', 'x="2"')
    (change,) = btd.diff_behavior_tree(before.encode("latin-1"), after.encode("latin-1"))
    assert change.line == 3


def test_attribute_values_cannot_break_out_of_markdown_code():
    after = BEFORE.replace(b'message="start"', b'message="a` [x](https://evil) `"')
    (change,) = btd.diff_behavior_tree(BEFORE, after)
    assert "`` a` [x](https://evil) ` ``" in change.message


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("wrap_block", {"added": 1, "changed": 1}),
        # Each matching rule in BehaviorTreeDiffer removes false moves from one of these.
        ("delete_block", {"removed": 1}),
        ("restructure_loop", {"added": 6, "moved": 4, "changed": 19, "removed": 1}),
        ("rename_waypoints", {"changed": 9}),
        ("rewrite_perception", {"added": 13, "changed": 9, "moved": 4, "removed": 12}),
    ],
)
def test_real_objective_revisions(name, expected):
    before = (FIXTURES / f"{name}.before.xml").read_bytes()
    after = (FIXTURES / f"{name}.after.xml").read_bytes()
    assert Counter(c.kind for c in btd.diff_behavior_tree(before, after)) == expected


def test_real_wrap_and_delete_read_as_one_line_each():
    def messages(name):
        before = (FIXTURES / f"{name}.before.xml").read_bytes()
        after = (FIXTURES / f"{name}.after.xml").read_bytes()
        return [c.message for c in btd.diff_behavior_tree(before, after) if c.kind != "changed"]

    assert messages("wrap_block") == [
        'Added `Decorator ID="ForceSuccess"`, wraps existing `Decorator ID="KeepRunningUntilFailure"`'
    ]
    assert messages("delete_block") == [
        'Removed `Control ID="Sequence"` with 3 more removed nodes from `Control ID="Sequence"`'
    ]


def test_move_into_a_new_wrapper_names_the_wrapper():
    before = b"""<root><BehaviorTree ID="T"><Control ID="Sequence">
<Action ID="A" />
<Action ID="B" />
<Control ID="Fallback">
<Action ID="C" />
</Control>
</Control></BehaviorTree></root>"""
    after = before.replace(b'<Action ID="B" />\n', b"").replace(
        b'<Action ID="C" />\n', b'<Action ID="C" />\n<Decorator ID="Retry"><Action ID="B" /></Decorator>\n'
    )
    moved = [c.message for c in btd.diff_behavior_tree(before, after) if c.kind == "moved"]
    assert moved == [
        (
            'Moved `Action ID="B"` from under `Control ID="Sequence"` (base line 1) into new '
            '`Decorator ID="Retry"` (line 5) under `Control ID="Fallback"` (line 3)'
        )
    ]


def test_an_edited_leaf_in_another_tree_is_a_remove_and_add():
    tree = b'<BehaviorTree ID="%s"><Control ID="Sequence"><Action ID="Keep" />%s</Control></BehaviorTree>'
    log = b'<Action ID="Log" level="info" message="%s" />'
    before = b"<root>" + tree % (b"T1", log % b"Waiting for approval") + tree % (b"T2", b"") + b"</root>"
    after = b"<root>" + tree % (b"T1", b"") + tree % (b"T2", log % b"Mission complete") + b"</root>"
    assert sorted(c.kind for c in btd.diff_behavior_tree(before, after)) == ["added", "removed"]


TREE = b'<root><BehaviorTree ID="T"><Control ID="Sequence">%s</Control></BehaviorTree></root>'


def test_swapping_look_alike_siblings_is_a_reorder_not_edits():
    pick = b'<SubTree ID="Move to Waypoint" waypoint_name="Pick Approach" />'
    place = b'<SubTree ID="Move to Waypoint" waypoint_name="Place Approach" />'
    assert kinds(btd.diff_behavior_tree(TREE % (pick + place), TREE % (place + pick))) == [
        ("reordered", 'Reordered children of `Control ID="Sequence"`')
    ]


def test_swapping_named_blocks_is_a_reorder_not_renames():
    one = b'<Control ID="Sequence" name="One"><Action ID="Log" message="a" /></Control>'
    two = b'<Control ID="Sequence" name="Two"><Action ID="Log" message="b" /></Control>'
    assert [c.kind for c in btd.diff_behavior_tree(TREE % (one + two), TREE % (two + one))] == ["reordered"]


def test_metadata_entries_match_by_their_keys():
    def model(*fields):
        return (
            b'<root><BehaviorTree ID="T"><Action ID="A" /></BehaviorTree><TreeNodesModel><SubTree ID="T">'
            b"<MetadataFields>" + b"".join(fields) + b"</MetadataFields></SubTree></TreeNodesModel></root>"
        )

    runnable, category = b'<Metadata runnable="true" />', b'<Metadata subcategory="Basic" />'
    swapped = btd.diff_behavior_tree(model(runnable, category), model(category, runnable))
    assert [c.kind for c in swapped] == ["reordered"]
    edited = btd.diff_behavior_tree(
        model(runnable, category), model(runnable, category.replace(b"Basic", b"Motion"))
    )
    assert kinds(edited) == [("changed", "Changed `Metadata` `subcategory`: `Basic` → `Motion`")]


def test_oversized_files_are_refused():
    huge = b'<root><BehaviorTree ID="T">' + b"<A />" * btd.MAX_NODES + b"</BehaviorTree></root>"
    with pytest.raises(ValueError, match="node limit"):
        btd.diff_behavior_tree(huge, huge)


def _repo(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    return git


def test_a_behavior_tree_that_stops_parsing_gets_a_warning(tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path)
    (tmp_path / "t.xml").write_bytes(BEFORE)
    git("add", ".")
    git("commit", "-qm", "base")
    (tmp_path / "t.xml").write_bytes(BEFORE.replace(b"</root>", b""))
    git("commit", "-qam", "head")
    monkeypatch.chdir(tmp_path)
    report = tmp_path / "summary.md"
    btd.main(["--base", "HEAD~1", "--head", "HEAD", "--report", str(report)])
    assert capsys.readouterr().out.startswith("::warning file=t.xml,")
    assert "Could not diff this file" in report.read_text()


def test_renamed_files_are_diffed_under_the_new_name(tmp_path, monkeypatch):
    git = _repo(tmp_path)
    (tmp_path / "old.xml").write_bytes(BEFORE)
    git("add", ".")
    git("commit", "-qm", "base")
    git("mv", "old.xml", "new name.xml")
    git("commit", "-qm", "head")
    monkeypatch.chdir(tmp_path)
    assert list(btd.changed_xml_files("HEAD~1", "HEAD")) == [("old.xml", "new name.xml")]


def test_annotations_are_capped_and_the_report_lists_everything(tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path)
    many = (
        b'<root><BehaviorTree ID="T"><Control ID="Sequence">\n'
        + b"".join(b'<Action ID="A%d" v="1" />\n' % n for n in range(12))
        + b"</Control></BehaviorTree></root>"
    )
    (tmp_path / "t.xml").write_bytes(many)
    git("add", ".")
    git("commit", "-qm", "base")
    (tmp_path / "t.xml").write_bytes(many.replace(b'v="1"', b'v="2"'))
    git("commit", "-qam", "head")
    monkeypatch.chdir(tmp_path)
    report = tmp_path / "summary.md"
    btd.main(["--base", "HEAD~1", "--head", "HEAD", "--report", str(report)])
    assert capsys.readouterr().out.count("::notice") == btd.MAX_ANNOTATIONS
    assert report.read_text().count("- Changed") == 12


def test_main_reports_behavior_tree_files_and_skips_other_xml(tmp_path, monkeypatch, capsys):
    git = _repo(tmp_path)
    objective = tmp_path / "objectives" / "pick.xml"
    objective.parent.mkdir()
    objective.write_bytes(BEFORE)
    (tmp_path / "package.xml").write_text("<package><name>a</name></package>")
    git("add", ".")
    git("commit", "-qm", "base")
    objective.write_bytes(WRAPPED)
    (tmp_path / "package.xml").write_text("<package><name>b</name></package>")
    git("commit", "-qam", "head")

    monkeypatch.chdir(tmp_path)
    report = tmp_path / "summary.md"
    assert (
        btd.main(
            [
                "--base",
                "HEAD~1",
                "--head",
                "HEAD",
                "--report",
                str(report),
                "--file-url",
                "https://x/blob/abc",
            ]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert out.startswith("::notice file=objectives/pick.xml,line=5,")
    text = report.read_text()
    assert "### `objectives/pick.xml`" in text
    assert "([L5](https://x/blob/abc/objectives/pick.xml#L5))" in text
    assert "package.xml" not in text
