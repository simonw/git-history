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

The `file` command analyzes the history of an individual file.

The command assumes you have a JSON file that consists of an array of objects, and that has multiple versions stored away in the Git history, likely through [Git scraping](https://simonwillison.net/2020/Oct/9/git-scraping/).

(CSV and other formats are supported too, see below.)

Most basic usage is:

    git-convert file database.db filename.json

This will create a new SQLite database in the `database.db` file with two tables:

- `commits` containing a row for every commit, with a `hash` column and the `commit_at` date.
- `items` containing a row for every item in every version of the `filename.json` file - with an extra `commit` column that is a foreign key back to the `commits` table.

More interesting is if you specify columns to be treated as IDs within that data, using the `--id` option one or more times. This allows the tool to track versions of each item as they change over time.

    git-convert file database.db filename.json --id IncidentID

If you do this, three tables will be created - `commits`, `items` and `item_versions`.

The `items` table will contain just the most recent version of each row, de-duplicated by ID.

The `item_versions` table will contain a row for each captured differing version of that item, plus the following columns:

- `item` as a foreign key to the `items` table
- `commit` as a foreign key to the `commits` table
- `version` as the numeric version number, starting at 1 and incrementing for each captured version

If you have already imported history, the command will skip any commits that it has seen already and just process new ones. This means that even though an initial import could be slow subsequent imports should run a lot faster.

Additional options:

- `--repo DIRECTORY` - the path to the Git repository, if it is not the current working directory.
- `--branch TEXT` - the Git branch to analyze - defaults to `main`.
- `--id TEXT` - as described above: pass one or more columns that uniquely identify a record, so that changes to that record can be calculated over time.
- `--ignore TEXT` - one or more columns to ignore - they will not be included in the resulting database.
- `--convert TEXT` - custom Python code for a conversion, see below.
- `--import TEXT` - Python modules to import for `--convert`.
- `--ignore-duplicate-ids` - if a single version of a file has the same ID in it more than once, the tool will exit with an error. Use this option to ignore this and instead pick just the first of the two duplicates.

Note that `id`, `item`, `version` and `commit` are reserved column names that are used by this tool. If your data contains any of these they will be renamed to `id_`, `item_`, `version_` or `commit_` to avoid clashing with the reserved columns.

There is one exception: if you have an `id` column and use `--id id` without specifying more than one ID column, your ìd` column will be used as the item ID but will not be renamed.

### CSV and TSV data

If the data in your repository is a CSV or TSV file you can process it by adding the `--csv` option. This will attempt to detect which delimiter is used by the file, so the same option works for both comma- and tab-separated values.

    git-convert file trees.db trees.csv --id TreeID

### Custom conversions using --convert

If your data is not already either CSV/TSV or a flat JSON array, you can reshape it using the `--convert` option.

The format needed by this tool is an array of dictionaries that looks like this:

```json
[
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
```

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

    git-convert file database.db incidents.json \
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
