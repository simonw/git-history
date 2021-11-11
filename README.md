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

This assumes you have a JSON file that consists of an array of objects, and that has multiple versions stored away in the Git history, likely through [Git scraping](https://simonwillison.net/2020/Oct/9/git-scraping/).

Most basic usage is:

    git-convert file database.db filename.json

This will create a new SQLite database in the `database.db` file with an `item` table containing row for every item in every version of the `filename.json` file - with extra columns `git_commit_at` and `git_hash`.

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
