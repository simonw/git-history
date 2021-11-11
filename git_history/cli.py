import click
import git
import json
import sqlite_utils
from pathlib import Path


def iterate_file_versions(repo_path, filepath, ref="main"):
    relative_path = str(Path(filepath).relative_to(repo_path))
    repo = git.Repo(repo_path, odbt=git.GitDB)
    commits = reversed(list(repo.iter_commits(ref, paths=[relative_path])))
    for commit in commits:
        try:
            blob = [b for b in commit.tree.blobs if b.name == relative_path][0]
            yield commit.committed_datetime, commit.hexsha, blob.data_stream.read()
        except IndexError:
            # This commit doesn't have a copy of the requested file
            pass



@click.group()
@click.version_option()
def cli():
    "Tools for analyzing Git history using SQLite"


@cli.command()
@click.argument(
    "database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.argument(
    "filepath",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.option(
    "--repo",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, allow_dash=False),
    default=".",
    help="Path to Git repo (if not current directory)",
)
@click.option("--branch", default="main", help="Git branch to use (defaults to main)")
@click.version_option()
def file(database, filepath, repo, branch, ids):
    "Analyze history of a specific file"
    resolved_filepath = str(Path(filepath).resolve())
    resolved_repo = str(Path(repo).resolve())
    db = sqlite_utils.Database(database)
    seen_hashes = set()
    for git_commit_at, git_hash, content in iterate_file_versions(
        resolved_repo, resolved_filepath, branch
    ):
        if git_hash not in seen_hashes:
            seen_hashes.add(git_hash)
            db["commits"].insert(
                {"hash": git_hash, "commit_at": git_commit_at.isoformat()},
                pk="hash",
                replace=True,
            )
        items = json.loads(content)
        for item in items:
            item["commit"] = git_hash
        db["items"].insert_all(
            items,
            alter=True,
            column_order=("commit",),
            foreign_keys=(("commit", "commits", "hash"),),
        )
