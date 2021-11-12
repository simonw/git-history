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
    git_commit = [
        "git",
        "-c",
        "user.name='Tests'",
        "-c",
        "user.email='actions@users.noreply.github.com'",
        "commit",
    ]
    subprocess.call(["git", "init"], cwd=str(repo_dir))
    subprocess.call(["git", "add", "items.json"], cwd=str(repo_dir))
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
