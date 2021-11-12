import click
import git
import hashlib
import json
import sqlite_utils
import textwrap
from pathlib import Path


def iterate_file_versions(
    repo_path, filepath, ref="main", skip_commits=None, show_progress=False
):
    relative_path = str(Path(filepath).relative_to(repo_path))
    repo = git.Repo(repo_path, odbt=git.GitDB)
    commits = reversed(list(repo.iter_commits(ref, paths=[relative_path])))
    progress_bar = None
    if skip_commits:
        # Filter down to just the ones we haven't seen
        new_commits = [
            commit for commit in commits if commit.hexsha not in skip_commits
        ]
        commits = new_commits
    if show_progress:
        progress_bar = click.progressbar(commits, show_pos=True, show_percent=True)
    for commit in commits:
        if progress_bar:
            progress_bar.update(1)
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
@click.option(
    "ids", "--id", multiple=True, help="Columns (can be multiple) to use as an ID"
)
@click.option("ignore", "--ignore", multiple=True, help="Columns to ignore")
@click.option(
    "csv_",
    "--csv",
    is_flag=True,
    help="Expect CSV/TSV data, not JSON",
)
@click.option(
    "--convert",
    help="Python code to read each file version content and return it as a list of dicts. Defaults to json.parse(content)",
)
@click.option(
    "--import",
    "imports",
    type=str,
    multiple=True,
    help="Python modules to import for --convert",
)
@click.option(
    "--ignore-duplicate-ids",
    is_flag=True,
    help="Keep going if same ID occurs more than once in a single version of a file",
)
@click.option(
    "--silent",
    is_flag=True,
    help="Don't show progress bar",
)
@click.version_option()
def file(
    database,
    filepath,
    repo,
    branch,
    ids,
    ignore,
    csv_,
    convert,
    imports,
    ignore_duplicate_ids,
    silent,
):
    "Analyze the history of a specific file and write it to SQLite"
    if csv_ and convert:
        raise click.ClickException("Cannot use both --csv and --convert")

    if csv_:
        convert = textwrap.dedent(
            """
            decoded = content.decode("utf-8")
            dialect = csv.Sniffer().sniff(decoded[:512])
            reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
            return list(reader)
        """
        )
        imports = ["io", "csv"]

    if not convert:
        convert = "json.loads(content)"

    # Clean up the provided code
    # If single line and no 'return', add the return
    if "\n" not in convert and not convert.strip().startswith("return "):
        convert = "return {}".format(convert)
    # Compile the code into a function body called fn(content)
    new_code = ["def fn(content):"]
    for line in convert.split("\n"):
        new_code.append("    {}".format(line))
    code_o = compile("\n".join(new_code), "<string>", "exec")
    locals = {}
    globals = {"json": json}
    for import_ in imports:
        globals[import_] = __import__(import_)
    exec(code_o, globals, locals)
    fn = locals["fn"]

    resolved_filepath = str(Path(filepath).resolve())
    resolved_repo = str(Path(repo).resolve())
    db = sqlite_utils.Database(database)
    seen_hashes = set()
    id_versions = {}
    id_last_hash = {}
    for git_commit_at, git_hash, content in iterate_file_versions(
        resolved_repo,
        resolved_filepath,
        branch,
        skip_commits=set(
            r[0] for r in db.execute("select hash from commits").fetchall()
        )
        if db["commits"].exists()
        else set(),
        show_progress=not silent,
    ):
        if git_hash not in seen_hashes:
            seen_hashes.add(git_hash)
            db["commits"].insert(
                {"hash": git_hash, "commit_at": git_commit_at.isoformat()},
                pk="hash",
                replace=True,
            )
        if not content.strip():
            # Skip empty JSON files
            continue

        items = fn(content)

        # Remove any --ignore columns
        if ignore:
            new_items = []
            for item in items:
                new_item = dict(
                    (key, value) for key, value in item.items() if key not in ignore
                )
                new_items.append(new_item)
            items = new_items

        items_insert_extra_kwargs = {}
        versions = []

        # If --id is specified, do things a bit differently
        if ids:
            # If '--id id' is only option, 'id' is not a reserved column
            id_is_reserved = list(ids) != ["id"]
            # Any ids that are reserved columns must be renamed
            fixed_ids = set(
                fix_reserved_columns(
                    {id: 1 for id in ids},
                    allow_id=not id_is_reserved,
                    allow_banned=True,
                ).keys()
            )
            items_insert_extra_kwargs["pk"] = "id"
            # Check all items have those columns
            _ids_set = set(ids)
            bad_items = [
                bad_item for bad_item in items if not _ids_set.issubset(bad_item.keys())
            ]
            if bad_items:
                raise click.ClickException(
                    "Commit: {} - every item must have the --id keys. These items did not:\n{}".format(
                        git_hash, json.dumps(bad_items[:5], indent=4, default=str)
                    )
                )
            # Also ensure there are not TWO items in this file with the same ID
            item_ids_in_this_version = set()
            items_to_add = []
            items_insert_extra_kwargs["replace"] = True
            # Which of these are new versions of things we have seen before
            for item in items:
                item = fix_reserved_columns(item, allow_id=not id_is_reserved)
                item_id = _hash(dict((id, item.get(id)) for id in fixed_ids))
                if item_id in item_ids_in_this_version:
                    if not ignore_duplicate_ids:
                        raise click.ClickException(
                            "Commit: {} - found multiple items with the same ID:\n{}".format(
                                git_hash,
                                json.dumps(
                                    [
                                        item
                                        for item in items
                                        if _hash(
                                            dict((id, item.get(id)) for id in fixed_ids)
                                        )
                                        == item_id
                                    ][:5],
                                    indent=4,
                                    default=str,
                                ),
                            )
                        )
                    else:
                        continue
                item_ids_in_this_version.add(item_id)
                # Has it changed since last time we saw it?
                item_hash = _hash(item)
                if id_last_hash.get(item_id) != item_hash:
                    # It's either new or the content has changed
                    id_last_hash[item_id] = item_hash
                    version = id_versions.get(item_id, 0) + 1
                    id_versions[item_id] = version
                    items_to_add.append(dict(item, id=item_id))
                    versions.append(
                        dict(item, item=item_id, version=version, commit=git_hash)
                    )

            # Only add the items that had no new version
            items = items_to_add

        else:
            # not ids - so just check them for banned columns and add the item["commit"]
            for item in items:
                item = fix_reserved_columns(item)
                item["commit"] = git_hash
            # In this case item table needs a foreign key on 'commit'
            items_insert_extra_kwargs["foreign_keys"] = (("commit", "commits", "hash"),)

        # insert items
        if items:
            db["items"].insert_all(
                items,
                column_order=("id",),
                alter=True,
                **items_insert_extra_kwargs,
            )

        # insert versions
        if versions:
            db["item_versions"].insert_all(
                versions,
                pk=("item", "version"),
                alter=True,
                replace=True,
                column_order=("item", "version", "commit"),
                foreign_keys=(("item", "items", "id"), ("commit", "commits", "hash")),
            )


def _hash(record):
    return hashlib.sha1(
        json.dumps(record, separators=(",", ":"), sort_keys=True, default=repr).encode(
            "utf8"
        )
    ).hexdigest()


def fix_reserved_columns(item, allow_id=False, allow_banned=False):
    reserved = {"item", "version", "commit", "rowid"}
    banned = {"id_", "item_", "version_", "commit_"}
    if not allow_id:
        reserved.add("id")
    if not allow_banned and any(key in banned for key in item):
        raise click.ClickException(
            "Column {} is one of these banned columns: {}\n{}".format(
                sorted([key for key in item if key in banned]),
                sorted(banned),
                json.dumps(item, indent=4, default=str),
            )
        )
    if not any(key in reserved for key in item):
        return item
    new_item = {}
    for key in item:
        if key in reserved:
            new_item[key + "_"] = item[key]
        else:
            new_item[key] = item[key]
    return new_item
