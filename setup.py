from setuptools import setup
import os

VERSION = "0.6.1"


def get_long_description():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md"),
        encoding="utf8",
    ) as fp:
        return fp.read()


setup(
    name="git-history",
    description="Tools for analyzing Git history using SQLite",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Simon Willison",
    url="https://github.com/simonw/git-history",
    project_urls={
        "Issues": "https://github.com/simonw/git-history/issues",
        "CI": "https://github.com/simonw/git-history/actions",
        "Changelog": "https://github.com/simonw/git-history/releases",
    },
    license="Apache License, Version 2.0",
    version=VERSION,
    packages=["git_history"],
    entry_points="""
        [console_scripts]
        git-history=git_history.cli:cli
    """,
    install_requires=["click", "GitPython", "sqlite-utils>=3.19"],
    extras_require={"test": ["pytest", "cogapp"]},
    python_requires=">=3.6",
)
