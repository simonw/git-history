# git-history

[![PyPI](https://img.shields.io/pypi/v/git-history.svg)](https://pypi.org/project/git-history/)
[![Changelog](https://img.shields.io/github/v/release/simonw/git-history?include_prereleases&label=changelog)](https://github.com/simonw/git-history/releases)
[![Tests](https://github.com/simonw/git-history/workflows/Test/badge.svg)](https://github.com/simonw/git-history/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/git-history/blob/master/LICENSE)

Tool for analyzing the Git history of a specific file using SQLite

## Installation

Install this tool using `pip`:

    $ pip install git-history

## Usage

Usage instructions go here.

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
