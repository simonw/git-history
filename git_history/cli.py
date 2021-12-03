import click
import git
import hashlib
import json
import sqlite_utils
import textwrap
from pathlib import Path
from .utils import fix_reserved_columns


def iterate_file_versions(
    repo_path, filepath, ref="main", commits_to_skip=None, show_progress=False
):
    relative_path = str(Path(filepath).relative_to(repo_path))
    repo = git.Repo(repo_path, odbt=git.GitDB)
    commits = reversed(list(repo.iter_commits(ref, paths=[relative_path])))
    progress_bar = None
    if commits_to_skip:
        # Filter down to just the ones we haven't seen
        new_commits = [
            commit for commit in commits if commit.hexsha not in commits_to_skip
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
@click.option(
    "-n",
    "--namespace",
    default="item",
    help="Used as part of the table names - defaults to item, but can be changed to use one database to store changes to more than one file",
)
@click.option("--branch", default="main", help="Git branch to use (defaults to main)")
@click.option(
    "ids", "--id", multiple=True, help="Columns (can be multiple) to use as an ID"
)
@click.option("--start-at", help="Skip commits prior to this one")
@click.option(
    "--start-after", help="Skip commits up to this one, then start at the next one"
)
@click.option(
    "skip_hashes", "--skip", multiple=True, help="Skip specific commit hashes"
)
@click.option(
    "--full-versions",
    is_flag=True,
    help="Record full copies in the item_version table, not just the columns that changed since the previous version",
)
@click.option("ignore", "--ignore", multiple=True, help="Columns to ignore")
@click.option(
    "csv_",
    "--csv",
    is_flag=True,
    help="Expect CSV/TSV data, not JSON",
)
@click.option(
    "--dialect",
    type=click.Choice(["excel", "excel-tab", "unix"]),
    help="CSV dialect to use - default is to auto-detect",
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
    namespace,
    branch,
    ids,
    ignore,
    start_at,
    start_after,
    skip_hashes,
    full_versions,
    csv_,
    dialect,
    convert,
    imports,
    ignore_duplicate_ids,
    silent,
):
    "Analyze the history of a specific file and write it to SQLite"
    if csv_ and convert:
        raise click.ClickException("Cannot use both --csv and --convert")

    if dialect:
        csv_ = True

    if start_at and start_after:
        raise click.ClickException(
            "Cannot use --start-at and --start-after at the same time"
        )

    db = sqlite_utils.Database(database)
    namespace_id = db["namespaces"].lookup({"name": namespace})

    commits_to_skip = (
        set(r[0] for r in db.execute("select hash from commits").fetchall())
        if db["commits"].exists()
        else set()
    )

    if skip_hashes:
        commits_to_skip.update(skip_hashes)

    item_table = namespace
    version_table = "{}_version".format(namespace)
    version_detail_view = "{}_version_detail".format(namespace)
    changed_table = "{}_changed".format(namespace)

    if csv_:
        convert = textwrap.dedent(
            """
            decoded = content.decode("utf-8")
            dialect = {}
            reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
            return reader
        """.format(
                '"{}"'.format(dialect)
                if dialect
                else "csv.Sniffer().sniff(decoded[:1024])"
            )
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

    item_id_to_version = {}
    item_id_to_last_full_hash = {}

    if db[version_table].exists():
        sql = """
        select
            item._item_id as item_id,
            max(item_version._version) as max_version,
            item_version._item_full_hash as item_full_hash
        from
            item_version
            join item on item_version._item = item._id
        group by
            _item_id
        """
        for row in db.query(sql):
            item_id_to_version[row["item_id"]] = row["max_version"]
            item_id_to_last_full_hash[row["item_id"]] = row["item_full_hash"]

    column_name_to_id = {}

    def column_id(column):
        if column not in column_name_to_id:
            id = db["columns"].lookup(
                {"namespace": namespace_id, "name": column},
                foreign_keys=(("namespace", "namespaces", "id"),),
            )
            column_name_to_id[column] = id
        return column_name_to_id[column]

    can_proceed = not (start_after or start_at)

    for git_commit_at, git_hash, content in iterate_file_versions(
        resolved_repo,
        resolved_filepath,
        branch,
        commits_to_skip=commits_to_skip,
        show_progress=not silent,
    ):
        if not can_proceed:
            if git_hash == start_after:
                can_proceed = True
                # But skip this one and start at the next one
                continue
            elif git_hash == start_at:
                can_proceed = True
            else:
                continue

        with db.conn:  # One transaction per git commit processed
            commit_id = db["commits"].lookup(
                {"namespace": namespace_id, "hash": git_hash},
                {"commit_at": git_commit_at.isoformat()},
                foreign_keys=(("namespace", "namespaces", "id"),),
            )
            if not content.strip():
                # Skip empty JSON files
                continue

            # list() to resolve generators for repeated access later
            items = list(fn(content))

            # Remove any --ignore columns
            if ignore:
                new_items = []
                for item in items:
                    new_item = dict(
                        (key, value) for key, value in item.items() if key not in ignore
                    )
                    new_items.append(new_item)
                items = new_items

            # If --id is specified, do things a bit differently
            if ids:
                # Any ids that are reserved columns must be renamed
                fixed_ids = set(
                    fix_reserved_columns(
                        {id: 1 for id in ids},
                    ).keys()
                )
                # Check all items have those columns
                _ids_set = set(ids)
                bad_items = [
                    bad_item
                    for bad_item in items
                    if not _ids_set.issubset(bad_item.keys())
                ]
                if bad_items:
                    raise click.ClickException(
                        "Commit: {} - every item must have the --id keys. These items did not:\n{}".format(
                            git_hash, json.dumps(bad_items[:5], indent=4, default=str)
                        )
                    )
                item_ids_in_this_commit = set()
                # Which of these are new versions of things we have seen before?
                for item in items:
                    item = fix_reserved_columns(item)
                    item_id = _hash(dict((id, item.get(id)) for id in fixed_ids))
                    if item_id in item_ids_in_this_commit:
                        # Ensure there are not TWO items in this commit with the same ID
                        if not ignore_duplicate_ids:
                            raise click.ClickException(
                                "Commit: {} - found multiple items with the same ID:\n{}".format(
                                    git_hash,
                                    json.dumps(
                                        [
                                            item
                                            for item in items
                                            if _hash(
                                                dict(
                                                    (id, item.get(id))
                                                    for id in fixed_ids
                                                )
                                            )
                                            == item_id
                                        ][:5],
                                        indent=4,
                                        default=str,
                                    ),
                                )
                            )
                        else:
                            # Skip this one
                            continue

                    item_ids_in_this_commit.add(item_id)

                    # Has it changed since last time we saw it?
                    item_full_hash = _hash(item)
                    item_is_new = item_id not in item_id_to_last_full_hash
                    item_full_hash_has_changed = (
                        item_id_to_last_full_hash.get(item_id) != item_full_hash
                    )

                    changed_columns = {}

                    if item_is_new or item_full_hash_has_changed:
                        # It's either new or the content has changed - so update item and insert an item_version
                        item_id_to_last_full_hash[item_id] = item_full_hash
                        version = item_id_to_version.get(item_id, 0) + 1
                        item_id_to_version[item_id] = version

                        # Add or fetch item
                        item_to_insert = dict(item, _item_id=item_id, _commit=commit_id)
                        item_pk = db[item_table].lookup(
                            {"_item_id": item_id},
                            item_to_insert,
                            column_order=("_id", "_item_id"),
                            pk="_id",
                        )

                        if full_versions:
                            # Record full copies in item_version
                            item_version = dict(
                                item, _item=item_pk, _version=version, _commit=commit_id
                            )
                        else:
                            # Only record the columns that have changed
                            if db[version_table].exists():
                                try:
                                    previous_item = list(
                                        db.query(
                                            """
                                        select * from {version_table} where _item = ?
                                        order by _version desc limit 1
                                        """.format(
                                                version_table=version_table,
                                                item_table=item_table,
                                            ),
                                            [item_pk],
                                        )
                                    )[0]
                                    changed_columns = {
                                        key: value
                                        for key, value in item.items()
                                        if (key not in previous_item)
                                        or previous_item[key] != value
                                    }
                                except IndexError:
                                    # First version of this item
                                    changed_columns = item
                            else:
                                changed_columns = item

                            item_version = dict(
                                changed_columns,
                                _item=item_pk,
                                _version=version,
                                _commit=commit_id,
                                _item_full_hash=item_full_hash,
                            )

                        item_version_id = (
                            db[version_table]
                            .insert(
                                item_version,
                                pk="_id",
                                alter=True,
                                replace=True,
                                column_order=("_item", "_version", "_commit"),
                                foreign_keys=(
                                    ("_item", item_table, "_id"),
                                    ("_commit", "commits", "id"),
                                ),
                            )
                            .last_pk
                        )

                        if changed_columns:
                            # Record which columns changed in the changed m2m table
                            db[changed_table].insert_all(
                                (
                                    {
                                        "item_version": item_version_id,
                                        "column": column_id(column),
                                    }
                                    for column in changed_columns
                                ),
                                pk=("item_version", "column"),
                                foreign_keys=(
                                    ("item_version", version_table, "_id"),
                                    ("column", "columns", "id"),
                                    ("namespace", "namespaces", "id"),
                                ),
                            )

            else:
                # no --id - so just correct for reserved columns and add item["_commit"]
                for item in items:
                    item = fix_reserved_columns(item)
                    item["_commit"] = commit_id
                # In this case item table needs a foreign key on 'commit'
                db[item_table].insert_all(
                    items,
                    column_order=("_id",),
                    alter=True,
                    foreign_keys=(("_commit", "commits", "id"),),
                )
    # Create any necessary views
    if db[version_table].exists():
        sql = textwrap.dedent(
            """
            select
                commits.commit_at as _commit_at,
                {version_table}.*,
                commits.hash as _commit_hash
            from
                {version_table}
                join commits on commits.id = {version_table}._commit""".format(
                version_table=version_table
            )
        ).strip()
        db.create_view(
            version_detail_view,
            sql,
            ignore=True,
        )


def _hash(record):
    return hashlib.sha1(
        json.dumps(record, separators=(",", ":"), sort_keys=True, default=repr).encode(
            "utf8"
        )
    ).hexdigest()
