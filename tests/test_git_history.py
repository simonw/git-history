from click.testing import CliRunner
from git_history.cli import cli
import json
import pytest
import subprocess
import sqlite_utils


@pytest.fixture
def repo(tmpdir):
    repo_dir = tmpdir / "repo"
    repo_dir.mkdir()
    (repo_dir / "items.json").write_text(
        json.dumps(
            [
                {
                    "item_id": 1,
                    "name": "Gin",
                },
                {
                    "item_id": 2,
                    "name": "Tonic",
                },
            ]
        ),
        "utf-8",
    )
    (repo_dir / "items-with-reserved-columns.json").write_text(
        json.dumps(
            [
                {
                    "_id": 1,
                    "_item": "Gin",
                    "_version": "v1",
                    "_commit": "commit1",
                    "rowid": 5,
                },
                {
                    "_id": 2,
                    "_item": "Tonic",
                    "_version": "v1",
                    "_commit": "commit1",
                    "rowid": 6,
                },
            ]
        ),
        "utf-8",
    )
    (repo_dir / "items-with-banned-columns.json").write_text(
        json.dumps(
            [
                {
                    "_id_": 1,
                    "_version_": "Gin",
                }
            ]
        ),
        "utf-8",
    )
    (repo_dir / "trees.csv").write_text(
        "TreeID,name\n1,Sophia\n2,Charlie",
        "utf-8",
    )
    (repo_dir / "trees.tsv").write_text(
        "TreeID\tname\n1\tSophia\n2\tCharlie",
        "utf-8",
    )
    git_commit = [
        "git",
        "-c",
        "user.name='Tests'",
        "-c",
        "user.email='actions@users.noreply.github.com'",
        "commit",
    ]
    subprocess.call(["git", "init"], cwd=str(repo_dir))
    subprocess.call(
        [
            "git",
            "add",
            "items.json",
            "items-with-reserved-columns.json",
            "items-with-banned-columns.json",
            "trees.csv",
            "trees.tsv",
        ],
        cwd=str(repo_dir),
    )
    subprocess.call(git_commit + ["-m", "first"], cwd=str(repo_dir))
    subprocess.call(["git", "branch", "-m", "main"], cwd=str(repo_dir))
    (repo_dir / "items.json").write_text(
        json.dumps(
            [
                {
                    "item_id": 1,
                    "name": "Gin",
                },
                {
                    "item_id": 2,
                    "name": "Tonic 2",
                },
                {
                    "item_id": 3,
                    "name": "Rum",
                },
            ]
        ),
        "utf-8",
    )
    (repo_dir / "items-with-reserved-columns.json").write_text(
        json.dumps(
            [
                {
                    "_id": 1,
                    "_item": "Gin",
                    "_version": "v1",
                    "_commit": "commit1",
                    "rowid": 5,
                },
                {
                    "_id": 2,
                    "_item": "Tonic 2",
                    "_version": "v1",
                    "_commit": "commit1",
                    "rowid": 6,
                },
                {
                    "_id": 3,
                    "_item": "Rum",
                    "_version": "v1",
                    "_commit": "commit1",
                    "rowid": 7,
                },
            ]
        ),
        "utf-8",
    )
    subprocess.call(git_commit + ["-m", "second", "-a"], cwd=str(repo_dir))
    return repo_dir


def test_file_without_id(repo, tmpdir):
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["file", db_path, str(repo / "items.json"), "--repo", str(repo)]
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commit] (\n"
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [hash] TEXT,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_commit_hash]\n"
        "    ON [commit] ([hash]);\n"
        "CREATE TABLE [item] (\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT,\n"
        "   [_commit] INTEGER REFERENCES [commit]([id])\n"
        ");"
    )
    assert db["commit"].count == 2
    # Should have some duplicates
    assert [(r["item_id"], r["name"]) for r in db["item"].rows] == [
        (1, "Gin"),
        (2, "Tonic"),
        (1, "Gin"),
        (2, "Tonic 2"),
        (3, "Rum"),
    ]


def test_file_with_id(repo, tmpdir):
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "file",
                db_path,
                str(repo / "items.json"),
                "--repo",
                str(repo),
                "--id",
                "item_id",
            ],
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commit] (\n"
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [hash] TEXT,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_commit_hash]\n"
        "    ON [commit] ([hash]);\n"
        "CREATE TABLE [item] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item_id] TEXT,\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT,\n"
        "   [_commit] INTEGER\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_item__item_id]\n"
        "    ON [item] ([_item_id]);\n"
        "CREATE TABLE [item_version] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item] INTEGER REFERENCES [item]([_id]),\n"
        "   [_version] INTEGER,\n"
        "   [_commit] INTEGER REFERENCES [commit]([id]),\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT\n"
        ");"
    )
    assert db["commit"].count == 2
    # Should have no duplicates
    item_version = [
        r for r in db.query("select item_id, _version, name from item_version")
    ]
    assert item_version == [
        {"item_id": 1, "_version": 1, "name": "Gin"},
        {"item_id": 2, "_version": 1, "name": "Tonic"},
        {"item_id": 2, "_version": 2, "name": "Tonic 2"},
        {"item_id": 3, "_version": 1, "name": "Rum"},
    ]


def test_file_with_reserved_columns(repo, tmpdir):
    runner = CliRunner()
    db_path = str(tmpdir / "reserved.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "file",
                db_path,
                str(repo / "items-with-reserved-columns.json"),
                "--repo",
                str(repo),
                "--id",
                "_id",
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commit] (\n"
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [hash] TEXT,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_commit_hash]\n"
        "    ON [commit] ([hash]);\n"
        "CREATE TABLE [item] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item_id] TEXT,\n"
        "   [_id_] INTEGER,\n"
        "   [_item_] TEXT,\n"
        "   [_version_] TEXT,\n"
        "   [_commit_] TEXT,\n"
        "   [rowid_] INTEGER,\n"
        "   [_commit] INTEGER\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_item__item_id]\n"
        "    ON [item] ([_item_id]);\n"
        "CREATE TABLE [item_version] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item] INTEGER REFERENCES [item]([_id]),\n"
        "   [_version] INTEGER,\n"
        "   [_commit] INTEGER REFERENCES [commit]([id]),\n"
        "   [_id_] INTEGER,\n"
        "   [_item_] TEXT,\n"
        "   [_version_] TEXT,\n"
        "   [_commit_] TEXT,\n"
        "   [rowid_] INTEGER\n"
        ");"
    )
    item_version = [
        r
        for r in db.query(
            "select _id_, _item_, _version_, _commit_, rowid_ from item_version"
        )
    ]
    assert item_version == [
        {
            "_id_": 1,
            "_item_": "Gin",
            "_version_": "v1",
            "_commit_": "commit1",
            "rowid_": 5,
        },
        {
            "_id_": 2,
            "_item_": "Tonic",
            "_version_": "v1",
            "_commit_": "commit1",
            "rowid_": 6,
        },
        {
            "_id_": 2,
            "_item_": "Tonic 2",
            "_version_": "v1",
            "_commit_": "commit1",
            "rowid_": 6,
        },
        {
            "_id_": 3,
            "_item_": "Rum",
            "_version_": "v1",
            "_commit_": "commit1",
            "rowid_": 7,
        },
    ]


@pytest.mark.parametrize("file", ("trees.csv", "trees.tsv"))
def test_csv_tsv(repo, tmpdir, file):
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "file",
                db_path,
                str(repo / file),
                "--repo",
                str(repo),
                "--id",
                "TreeID",
                "--csv",
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commit] (\n"
        "   [id] INTEGER PRIMARY KEY,\n"
        "   [hash] TEXT,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_commit_hash]\n"
        "    ON [commit] ([hash]);\n"
        "CREATE TABLE [item] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item_id] TEXT,\n"
        "   [TreeID] TEXT,\n"
        "   [name] TEXT,\n"
        "   [_commit] INTEGER\n"
        ");\n"
        "CREATE UNIQUE INDEX [idx_item__item_id]\n"
        "    ON [item] ([_item_id]);\n"
        "CREATE TABLE [item_version] (\n"
        "   [_id] INTEGER PRIMARY KEY,\n"
        "   [_item] INTEGER REFERENCES [item]([_id]),\n"
        "   [_version] INTEGER,\n"
        "   [_commit] INTEGER REFERENCES [commit]([id]),\n"
        "   [TreeID] TEXT,\n"
        "   [name] TEXT\n"
        ");"
    )


@pytest.mark.parametrize(
    "convert,expected_rows",
    (
        (
            "json.loads(content.upper())",
            [
                {"ITEM_ID": 1, "NAME": "GIN"},
                {"ITEM_ID": 2, "NAME": "TONIC"},
                {"ITEM_ID": 1, "NAME": "GIN"},
                {"ITEM_ID": 2, "NAME": "TONIC 2"},
                {"ITEM_ID": 3, "NAME": "RUM"},
            ],
        ),
        # Generator
        (
            (
                "data = json.loads(content)\n"
                "for item in data:\n"
                '    yield {"just_name": item["name"]}'
            ),
            [
                {"just_name": "Gin"},
                {"just_name": "Tonic"},
                {"just_name": "Gin"},
                {"just_name": "Tonic 2"},
                {"just_name": "Rum"},
            ],
        ),
    ),
)
def test_convert(repo, tmpdir, convert, expected_rows):
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "file",
                db_path,
                str(repo / "items.json"),
                "--repo",
                str(repo),
                "--convert",
                convert,
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    rows = [{k: v for k, v in r.items() if k != "_commit"} for r in db["item"].rows]
    assert rows == expected_rows
