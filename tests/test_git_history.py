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
                {"id": 1, "item": "Gin", "version": "v1", "commit": "commit1"},
                {"id": 2, "item": "Tonic", "version": "v1", "commit": "commit1"},
            ]
        ),
        "utf-8",
    )
    (repo_dir / "items-with-banned-columns.json").write_text(
        json.dumps(
            [
                {
                    "id_": 1,
                    "version_": "Gin",
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
                {"id": 1, "item": "Gin", "version": "v1", "commit": "commit1"},
                {"id": 2, "item": "Tonic 2", "version": "v1", "commit": "commit1"},
                {"id": 3, "item": "Rum", "version": "v1", "commit": "commit1"},
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
        "CREATE TABLE [commits] (\n"
        "   [hash] TEXT PRIMARY KEY,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE TABLE [items] (\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT,\n"
        "   [commit] TEXT REFERENCES [commits]([hash])\n"
        ");"
    )
    assert db["commits"].count == 2
    # Should have some duplicates
    assert [(r["item_id"], r["name"]) for r in db["items"].rows] == [
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
        "CREATE TABLE [commits] (\n"
        "   [hash] TEXT PRIMARY KEY,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE TABLE [items] (\n"
        "   [id] TEXT PRIMARY KEY,\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT\n"
        ");\n"
        "CREATE TABLE [item_versions] (\n"
        "   [item] TEXT REFERENCES [items]([id]),\n"
        "   [version] INTEGER,\n"
        "   [commit] TEXT REFERENCES [commits]([hash]),\n"
        "   [item_id] INTEGER,\n"
        "   [name] TEXT,\n"
        "   PRIMARY KEY ([item], [version])\n"
        ");"
    )
    assert db["commits"].count == 2
    # Should have no duplicates
    item_versions = [
        r for r in db.query("select item_id, version, name from item_versions")
    ]
    assert item_versions == [
        {"item_id": 1, "version": 1, "name": "Gin"},
        {"item_id": 2, "version": 1, "name": "Tonic"},
        {"item_id": 2, "version": 2, "name": "Tonic 2"},
        {"item_id": 3, "version": 1, "name": "Rum"},
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
                "id",
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commits] (\n"
        "   [hash] TEXT PRIMARY KEY,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE TABLE [items] (\n"
        "   [id] TEXT PRIMARY KEY,\n"
        "   [item_] TEXT,\n"
        "   [version_] TEXT,\n"
        "   [commit_] TEXT\n"
        ");\n"
        "CREATE TABLE [item_versions] (\n"
        "   [item] TEXT REFERENCES [items]([id]),\n"
        "   [version] INTEGER,\n"
        "   [commit] TEXT REFERENCES [commits]([hash]),\n"
        "   [id] INTEGER,\n"
        "   [item_] TEXT,\n"
        "   [version_] TEXT,\n"
        "   [commit_] TEXT,\n"
        "   PRIMARY KEY ([item], [version])\n"
        ");"
    )
    item_versions = [
        r for r in db.query("select id, item_, version_, commit_ from item_versions")
    ]
    assert item_versions == [
        {"id": 1, "item_": "Gin", "version_": "v1", "commit_": "commit1"},
        {"id": 2, "item_": "Tonic", "version_": "v1", "commit_": "commit1"},
        {"id": 2, "item_": "Tonic 2", "version_": "v1", "commit_": "commit1"},
        {"id": 3, "item_": "Rum", "version_": "v1", "commit_": "commit1"},
    ]


def test_more_than_one_id_makes_id_reserved(repo, tmpdir):
    # If we use "--id id --id version" then id is converted to id_
    # so we can add our own id_ that is a hash of those two columns
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
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
                "id",
                "--id",
                "version",
            ],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    db = sqlite_utils.Database(db_path)
    assert db.schema == (
        "CREATE TABLE [commits] (\n"
        "   [hash] TEXT PRIMARY KEY,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE TABLE [items] (\n"
        "   [id] TEXT PRIMARY KEY,\n"
        "   [id_] INTEGER,\n"
        "   [item_] TEXT,\n"
        "   [version_] TEXT,\n"
        "   [commit_] TEXT\n"
        ");\n"
        "CREATE TABLE [item_versions] (\n"
        "   [item] TEXT REFERENCES [items]([id]),\n"
        "   [version] INTEGER,\n"
        "   [commit] TEXT REFERENCES [commits]([hash]),\n"
        "   [id_] INTEGER,\n"
        "   [item_] TEXT,\n"
        "   [version_] TEXT,\n"
        "   [commit_] TEXT,\n"
        "   PRIMARY KEY ([item], [version])\n"
        ");"
    )


@pytest.mark.parametrize("specify_id", (True, False))
def test_file_with_banned_columns(repo, tmpdir, specify_id):
    runner = CliRunner()
    db_path = str(tmpdir / "db.db")
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "file",
                db_path,
                str(repo / "items-with-banned-columns.json"),
                "--repo",
                str(repo),
            ]
            + (["--id", "id_"] if specify_id else []),
            catch_exceptions=False,
        )
    assert result.exit_code == 1
    assert result.output.strip() == (
        "Error: Column ['id_', 'version_'] is one of these banned columns: ['commit_', 'id_', 'item_', 'version_']\n"
        "{\n"
        '    "id_": 1,\n'
        '    "version_": "Gin"\n'
        "}"
    )


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
        "CREATE TABLE [commits] (\n"
        "   [hash] TEXT PRIMARY KEY,\n"
        "   [commit_at] TEXT\n"
        ");\n"
        "CREATE TABLE [items] (\n"
        "   [id] TEXT PRIMARY KEY,\n"
        "   [TreeID] TEXT,\n"
        "   [name] TEXT\n"
        ");\n"
        "CREATE TABLE [item_versions] (\n"
        "   [item] TEXT REFERENCES [items]([id]),\n"
        "   [version] INTEGER,\n"
        "   [commit] TEXT REFERENCES [commits]([hash]),\n"
        "   [TreeID] TEXT,\n"
        "   [name] TEXT,\n"
        "   PRIMARY KEY ([item], [version])\n"
        ");"
    )
