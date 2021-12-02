from click import Option
from git_history.cli import file
import pathlib
import pytest


file_options = [p for p in file.params if isinstance(p, Option)]
long_forms = []
for file_option in file_options:
    for opt in file_option.opts:
        if opt.startswith("--") and opt != "--version":
            long_forms.append(opt)

readme = (pathlib.Path(__file__).parent / ".." / "README.md").read_text()


@pytest.mark.parametrize("option", long_forms)
def test_file_options_are_documented(option):
    assert option in readme
