# git-history

[![PyPI](https://img.shields.io/pypi/v/git-history.svg)](https://pypi.org/project/git-history/)
[![Changelog](https://img.shields.io/github/v/release/simonw/git-history?include_prereleases&label=changelog)](https://github.com/simonw/git-history/releases)
[![Tests](https://github.com/simonw/git-history/workflows/Test/badge.svg)](https://github.com/simonw/git-history/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/git-history/blob/master/LICENSE)

Tools for analyzing Git history using SQLite

## Installation

Install this tool using `pip`:

    $ pip install git-history

## Usage

This tool can be run against a Git repository that holds a file that contains JSON, CSV/TSV or some other format and which has multiple versions tracked in the Git history. See [Git scraping](https://simonwillison.net/2020/Oct/9/git-scraping/) to understand how you might create such a repository.

The `file` command analyzes the history of an individual file within the repository, and generates a SQLite database table that represents the different versions of that file over time.

The file is assumed to contain multiple objects - for example, the results of scraping an electricity outage map or a CSV file full of records.

Assuming you have a file called `incidents.json` that is a JSON array of objects, with multiple versions of that file recorded in a repository. Each version of that file might look something like this:

```json
[
    {
        "IncidentID": "abc123",
        "Location": "Corner of 4th and Vermont",
        "Type": "fire"
    },
    {
        "IncidentID": "cde448",
        "Location": "555 West Example Drive",
        "Type": "medical"
    }
]
```

Change directory into the GitHub repository in question and run the following:

    git-history file incidents.db incidents.json

This will create a new SQLite database in the `incidents.db` file with two tables:

- `commit` containing a row for every commit, with a `hash` column and the `commit_at` date.
- `item` containing a row for every item in every version of the `filename.json` file - with an extra `_commit` column that is a foreign key back to the `commit` table.

The database schema for this example will look like this:

<!-- [[[cog
import cog, json
from git_history import cli
from click.testing import CliRunner
from tests.test_git_history import make_repo
import sqlite_utils
import tempfile, pathlib
tmpdir = pathlib.Path(tempfile.mkdtemp())
db_path = str(tmpdir / "data.db")
make_repo(tmpdir)
runner = CliRunner()
result = runner.invoke(cli.cli, [
    "file", db_path, str(tmpdir / "repo" / "incidents.json"), "--repo", str(tmpdir / "repo")
])
cog.out("```sql\n")
cog.out(sqlite_utils.Database(db_path).schema)
cog.out("\n```")
]]] -->
```sql
CREATE TABLE [namespaces] (
   [id] INTEGER PRIMARY KEY,
   [name] TEXT
);
CREATE UNIQUE INDEX [idx_namespaces_name]
    ON [namespaces] ([name]);
CREATE TABLE [commits] (
   [id] INTEGER PRIMARY KEY,
   [namespace] INTEGER REFERENCES [namespaces]([id]),
   [hash] TEXT,
   [commit_at] TEXT
);
CREATE UNIQUE INDEX [idx_commits_namespace_hash]
    ON [commits] ([namespace], [hash]);
CREATE TABLE [item] (
   [IncidentID] TEXT,
   [Location] TEXT,
   [Type] TEXT,
   [_commit] INTEGER REFERENCES [commits]([id])
);
```
<!-- [[[end]]] -->

If you have 10 historic versions of the `incidents.json` file and each one contains 30 incidents, you will end up with 10 * 30 = 300 rows in your `item` table.

### De-duplicating items using IDs

If your objects have a unique identifier - or multiple columns that together form a unique identifier - you can use the `--id` option to de-duplicate and track changes to each of those items over time.

If there is a unique identifier column called `IncidentID` you could run the following:

    git-history file incidents.db incidents.json --id IncidentID

This will create three tables - `commit`, `item` and `item_version`.

This time the schema will look like this:

<!-- [[[cog
db_path2 = str(tmpdir / "data2.db")
result = runner.invoke(cli.cli, [
    "file", db_path2, str(tmpdir / "repo" / "incidents.json"),
    "--repo", str(tmpdir / "repo"),
    "--id", "IncidentID"
])
cog.out("```sql\n")
cog.out(sqlite_utils.Database(db_path2).schema)
cog.out("\n```")
]]] -->
```sql
CREATE TABLE [namespaces] (
   [id] INTEGER PRIMARY KEY,
   [name] TEXT
);
CREATE UNIQUE INDEX [idx_namespaces_name]
    ON [namespaces] ([name]);
CREATE TABLE [commits] (
   [id] INTEGER PRIMARY KEY,
   [namespace] INTEGER REFERENCES [namespaces]([id]),
   [hash] TEXT,
   [commit_at] TEXT
);
CREATE UNIQUE INDEX [idx_commits_namespace_hash]
    ON [commits] ([namespace], [hash]);
CREATE TABLE [item] (
   [_id] INTEGER PRIMARY KEY,
   [_item_id] TEXT,
   [IncidentID] TEXT,
   [Location] TEXT,
   [Type] TEXT,
   [_commit] INTEGER
);
CREATE UNIQUE INDEX [idx_item__item_id]
    ON [item] ([_item_id]);
CREATE TABLE [item_version] (
   [_id] INTEGER PRIMARY KEY,
   [_item] INTEGER REFERENCES [item]([_id]),
   [_version] INTEGER,
   [_commit] INTEGER REFERENCES [commits]([id]),
   [IncidentID] TEXT,
   [Location] TEXT,
   [Type] TEXT
);
```
<!-- [[[end]]] -->

The `item` table will contain the most recent version of each row, de-duplicated by ID, plus the following additional columns:

- `_id` - a numeric integer primary key, used as a foreign key from the `item_version` table.
- `_item_id` - a hash of the values of the columns specified using the `--id` option to the command. This is used for de-duplication when processing new versions.
- `_commit` - a foreign key to the `commit` table.

The `item_version` table will contain a row for each captured differing version of that item, plus the following columns:

- `_item` - a foreign key to the `item` table.
- `_version` - the numeric version number, starting at 1 and incrementing for each captured version.
- `_commit` - a foreign key to the `commit` table.

If you have already imported history, the command will skip any commits that it has seen already and just process new ones. This means that even though an initial import could be slow subsequent imports should run a lot faster.

Additional options:

- `--repo DIRECTORY` - the path to the Git repository, if it is not the current working directory.
- `--branch TEXT` - the Git branch to analyze - defaults to `main`.
- `--id TEXT` - as described above: pass one or more columns that uniquely identify a record, so that changes to that record can be calculated over time.
- `--ignore TEXT` - one or more columns to ignore - they will not be included in the resulting database.
- `--csv` - treat the data is CSV or TSV rather than JSON, and attempt to guess the correct dialect
- `--convert TEXT` - custom Python code for a conversion, see below.
- `--import TEXT` - Python modules to import for `--convert`.
- `--ignore-duplicate-ids` - if a single version of a file has the same ID in it more than once, the tool will exit with an error. Use this option to ignore this and instead pick just the first of the two duplicates.
- `--silent` - don't show the progress bar.

Note that `_id`, `_item`, `_version`, `_commit` and `rowid` are considered column names for the purposes of this tool. If your data contains any of these they will be renamed to `_id_`, `_item_`, `_version_`, `_commit_` or `_rowid_` to avoid clashing with the reserved columns.

If you have a column with a name such as `_commit_` it will be renamed too, adding an additional trailing underscore, so `_commit_` becomes `_commit__` and `_commit__` becomes `_commit__`.

### CSV and TSV data

If the data in your repository is a CSV or TSV file you can process it by adding the `--csv` option. This will attempt to detect which delimiter is used by the file, so the same option works for both comma- and tab-separated values.

    git-history file trees.db trees.csv --id TreeID

### Custom conversions using --convert

If your data is not already either CSV/TSV or a flat JSON array, you can reshape it using the `--convert` option.

The format needed by this tool is an array of dictionaries, as demonstrated by the `incidents.json` example above.

If your data does not fit this shape, you can provide a snippet of Python code to converts the on-disk content of each stored file into a Python list of dictionaries.

For example, if your stored files each look like this:

```json
{
    "incidents": [
        {
            "id": "552",
            "name": "Hawthorne Fire",
            "engines": 3
        },
        {
            "id": "556",
            "name": "Merlin Fire",
            "engines": 1
        }
    ]
}
```
You could use the following Python snippet to convert them to the required format:

```python
json.loads(content)["incidents"]
```
(The `json` module is exposed to your custom function by default.)

You would then run the tool like this:

    git-history file database.db incidents.json \
      --id id \
      --convert 'json.loads(content)["incidents"]'

The `content` variable is always a `bytes` object representing the content of the file at a specific moment in the repository's history.

You can import additional modules using `--import`. This example shows how you could read a CSV file that uses `;` as the delimiter:

    git-history file trees.db ../sf-tree-history/Street_Tree_List.csv \
      --repo ../sf-tree-history \
      --import csv \
      --import io \
      --convert '
        fp = io.StringIO(content.decode("utf-8"))
        return list(csv.DictReader(fp, delimiter=";"))
        ' \
      --id TreeID

If your Python code spans more than one line it needs to include a `return` statement.

You can also use Python generators in your `--convert` code, for example:

    git-history file stats.db package-stats/stats.json \
        --repo package-stats \
        --convert '
        data = json.loads(content)
        for key, counts in data.items():
            for date, count in counts.items():
                yield {
                    "package": key,
                    "date": date,
                    "count": count
                }
        ' --id package --id date

This conversion function expects data that looks like this:

```json
{
    "airtable-export": {
        "2021-05-18": 66,
        "2021-05-19": 60,
        "2021-05-20": 87
    }
}
```

## Development

To contribute to this tool, first checkout the code. Then create a new virtual environment:

    cd git-history
    python -m venv venv
    source venv/bin/activate

Or if you are using `pipenv`:

    pipenv shell

Now install the dependencies and test dependencies:

    pip install -e '.[test]'

To run the tests:

    pytest

To update the schema examples in this README file:

    cog -r README.md
