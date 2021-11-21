from git_history.utils import fix_reserved_columns
import pytest


@pytest.mark.parametrize(
    "column,expected",
    (
        ("_id", "_id_"),
        ("_item", "_item_"),
        ("_version", "_version_"),
        ("_commit", "_commit_"),
        ("_item_id", "_item_id_"),
        ("rowid", "rowid_"),
        ("rowid_", "rowid__"),
        ("_id__", "_id___"),
    ),
)
def test_fix_reserved_columns(column, expected):
    item = {column: 1}
    fixed = fix_reserved_columns(item)
    assert fixed == {expected: 1}
    assert item is not fixed


def test_fix_reserved_columns_unchanged_if_no_reserved():
    item = {"id": 1, "version": "v2"}
    fixed = fix_reserved_columns(item)
    assert item is fixed
