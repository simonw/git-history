import click
import git
import hashlib
import json
import sqlite_utils
import textwrap
from pathlib import Path
from .utils import RESERVED_SET, fix_reserved_columns, jsonify_if_needed


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
    "--wal",
    is_flag=True,
    help="Enable WAL mode on the created database file",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Debug mode",
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
    wal,
    debug,
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
    if wal:
        db.enable_wal()

    namespace_id = db["namespaces"].lookup({"name": namespace})

    commits_to_skip = get_commit_hashes(db, namespace)
    if skip_hashes:
        commits_to_skip.update(skip_hashes)

    item_table = namespace
    version_table = "{}_version".format(namespace)
    version_detail_view = "{}_version_detail".format(namespace)
    changed_table = "{}_changed".format(namespace)

    if csv_:
        convert = build_csv_convert_string(dialect)
        imports = ["io", "csv"]

    if not convert:
        convert = "json.loads(content)"

    convert_function = compile_convert(convert, imports)

    resolved_filepath = str(Path(filepath).resolve())
    resolved_repo = str(Path(repo).resolve())

    # In-memory caches of the most recent version and last full hash for each item_id
    item_id_to_version, item_id_to_last_full_hash = get_versions_and_hashes(
        db, namespace
    )

    # In-memory cache for db["columns"].lookup(...)
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

        if True:  # with db.conn:  # One transaction per git commit processed
            commit_pk = db["commits"].lookup(
                {"namespace": namespace_id, "hash": git_hash},
                {"commit_at": git_commit_at.isoformat()},
                foreign_keys=(("namespace", "namespaces", "id"),),
            )
            if not content.strip():
                # Skip empty files
                continue

            # list() to resolve generators for repeated access later
            try:
                items = list(convert_function(content))
            except Exception:
                print("\nError in commit: {}".format(git_hash))
                raise

            # Remove any --ignore columns
            items = remove_ignore_columns(items, ignore)

            if not ids:
                # no --id - so just populate item_table and add item["_commit"]
                for item in items:
                    item = jsonify_all(fix_reserved_columns(item))
                    item["_commit"] = commit_pk
                db[item_table].insert_all(
                    items,
                    column_order=("_id",),
                    alter=True,
                    foreign_keys=(("_commit", "commits", "id"),),
                )
            else:
                # --id is specified, so populate item_version with changes over time
                # Any --id that is a reserved column needs to be renamed first
                fixed_ids = set(
                    fix_reserved_columns(
                        {id: 1 for id in ids},
                    ).keys()
                )
                # Validate all items in the commit have ID columns - raises ClickException if not
                validate_items_have_id_columns(items, ids, git_hash)

                # Use this to detect IDs that are duplicated in the same commit
                item_ids_seen_in_this_commit = set()

                # Which of these are new versions of things we have seen before?
                for item in items:
                    item = fix_reserved_columns(item)
                    item_id = _hash(dict((id, item.get(id)) for id in fixed_ids))
                    if item_id in item_ids_seen_in_this_commit:
                        # Ensure there are not multiple items in this commit with the same ID
                        if not ignore_duplicate_ids:
                            raise DuplicateIdsException(
                                git_hash, items, fixed_ids, item_id
                            )
                        else:
                            # Skip this one
                            continue

                    item_ids_seen_in_this_commit.add(item_id)

                    # Has it changed since last time we saw it?
                    item_full_hash = _hash(item)

                    # JSONify any lists/dicts to assist later comparison with row from DB
                    item_flattened = jsonify_all(item)

                    if debug:
                        db["debug"].insert(
                            {
                                "hash": item_full_hash,
                                "content": json.dumps(
                                    item, default=repr, sort_keys=True
                                ),
                            },
                            pk="hash",
                            replace=True,
                        )

                    item_is_new = item_id not in item_id_to_last_full_hash
                    item_full_hash_has_changed = (
                        item_id_to_last_full_hash.get(item_id) != item_full_hash
                    )

                    updated_values = {}
                    updated_columns = set()

                    if item_is_new or item_full_hash_has_changed:
                        # TODO: delete-me
                        previous_item_hash = item_id_to_last_full_hash.get(item_id)

                        # It's either new or the content has changed - so update item and insert an item_version
                        item_id_to_last_full_hash[item_id] = item_full_hash
                        version = item_id_to_version.get(item_id, 0) + 1
                        item_id_to_version[item_id] = version

                        previous_item = None
                        if not item_is_new:
                            previous_item = get_item(db, item_table, item_id)

                        # Add or update item
                        item_pk = db[item_table].lookup(
                            {"_item_id": item_id},
                            column_order=("_id", "_item_id"),
                            foreign_keys=(("_commit", "commits", "id"),),
                            pk="_id",
                        )
                        db[item_table].update(
                            item_pk,
                            dict(item_flattened, _item_id=item_id, _commit=commit_pk),
                            alter=True,
                        )

                        if full_versions:
                            # Record full copies in item_version
                            item_version = dict(
                                item_flattened,
                                _item=item_pk,
                                _version=version,
                                _commit=commit_pk,
                            )
                        else:
                            # Only record the columns that have changed
                            if previous_item is not None:
                                for column in (
                                    item_flattened.keys() | previous_item.keys()
                                ):
                                    if column in RESERVED_SET:
                                        continue
                                    value = item_flattened.get(column)
                                    if value != previous_item.get(column):
                                        updated_values[column] = value
                                        updated_columns.add(column)
                            else:
                                updated_values = item_flattened
                                updated_columns.update(item_flattened.keys())

                            item_version = dict(
                                updated_values,
                                _item=item_pk,
                                _version=version,
                                _commit=commit_pk,
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

                        if updated_columns:
                            # Record which columns changed in the changed m2m table
                            db[changed_table].insert_all(
                                (
                                    {
                                        "item_version": item_version_id,
                                        "column": column_id(column),
                                    }
                                    for column in updated_columns
                                ),
                                pk=("item_version", "column"),
                                foreign_keys=(
                                    ("item_version", version_table, "_id"),
                                    ("column", "columns", "id"),
                                    ("namespace", "namespaces", "id"),
                                ),
                            )
                        else:
                            # ERROR: full has changed but no visible changes?
                            if not item_is_new and not full_versions and debug:
                                print(
                                    "Potential bug: hashchanged but no updated_columns"
                                )
                                import pdb

                                pdb.set_trace()
                                assert False

    # Create any necessary views
    create_views(db, namespace)
    # ... and indexes
    if db[version_table].exists():
        db[version_table].create_index(["_item"], if_not_exists=True)


def _hash(record):
    return hashlib.sha1(
        json.dumps(record, separators=(",", ":"), sort_keys=True, default=repr).encode(
            "utf8"
        )
    ).hexdigest()


def jsonify_all(item):
    return {key: jsonify_if_needed(value) for key, value in item.items()}


def get_item(db, item_table, item_id):
    previous_items = list(
        db.query(
            """
        select * from [{item_table}] where _item_id = ?
        """.format(
                item_table=item_table,
            ),
            [item_id],
        )
    )
    if previous_items:
        return previous_items[0]
    else:
        return None


def build_csv_convert_string(dialect):
    return textwrap.dedent(
        """
        decoded = content.decode("utf-8")
        dialect = {}
        reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
        return reader
        """.format(
            '"{}"'.format(dialect) if dialect else "csv.Sniffer().sniff(decoded[:1024])"
        )
    ).strip()


def compile_convert(convert, imports):
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
        globals[import_.split(".")[0]] = __import__(import_)
    exec(code_o, globals, locals)
    return locals["fn"]


def remove_ignore_columns(items, ignore):
    if ignore:
        new_items = []
        for item in items:
            new_item = dict(
                (key, value) for key, value in item.items() if key not in ignore
            )
            new_items.append(new_item)
        return new_items
    else:
        return items


def create_views(db, namespace):
    if db["{}_version".format(namespace)].exists():
        sql = textwrap.dedent(
            """
            select
              commits.commit_at as _commit_at,
              commits.hash as _commit_hash,
              {namespace}_version.*,
              (
                select json_group_array(name) from columns
                where id in (
                  select column from {namespace}_changed
                  where item_version = {namespace}_version._id
                )
            ) as _changed_columns
            from {namespace}_version
              join commits on commits.id = {namespace}_version._commit
            """.format(
                namespace=namespace
            )
        ).strip()
        db.create_view(
            "{namespace}_version_detail".format(namespace=namespace),
            sql,
            ignore=True,
        )


def get_commit_hashes(db, namespace):
    return (
        set(
            r[0]
            for r in db.execute(
                """
            select hash from commits
            where namespace = (
                select id from namespaces where name = ?
            )
        """,
                [namespace],
            ).fetchall()
        )
        if db["commits"].exists()
        else set()
    )


def get_versions_and_hashes(db, namespace):
    item_id_to_version = {}
    item_id_to_last_full_hash = {}
    if db[namespace + "_version"].exists():
        sql = """
        select
            {namespace}._item_id as item_id,
            max({namespace}_version._version) as max_version,
            {namespace}_version._item_full_hash as item_full_hash
        from
            {namespace}_version
            join {namespace} on {namespace}_version._item = {namespace}._id
        group by
            _item_id
        """.format(
            namespace=namespace
        )
        for row in db.query(sql):
            item_id_to_version[row["item_id"]] = row["max_version"]
            item_id_to_last_full_hash[row["item_id"]] = row["item_full_hash"]
    return item_id_to_version, item_id_to_last_full_hash


def validate_items_have_id_columns(items, ids, git_hash):
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


class DuplicateIdsException(click.ClickException):
    def __init__(self, git_hash, items, fixed_ids, item_id):
        message = "Commit: {} - found multiple items with the same ID:\n{}".format(
            git_hash,
            json.dumps(
                [
                    item
                    for item in items
                    if _hash(dict((id, item.get(id)) for id in fixed_ids)) == item_id
                ][:5],
                indent=4,
                default=str,
            ),
        )
        super().__init__(message)
