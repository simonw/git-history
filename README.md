# Template repository for creating new Python Click CLI tools

This GitHub [template repository](https://docs.github.com/en/github/creating-cloning-and-archiving-repositories/creating-a-repository-on-github/creating-a-repository-from-a-template) can be used to create a new repository with the skeleton of a Python [Click](https://click.palletsprojects.com/) CLI tool, based on the [click-app](https://github.com/simonw/click-app) cookiecutter.

Start here: https://github.com/simonw/click-app-template-repository/generate

The name of your repository will be the name of the CLI tool, and also the name of the Python package that you publish to [PyPI](https://pypi.org/) - so make sure that name is not taken already!

Add a one-line description of your CLI tool, then click "Create repository from template".

![Screenshot of the create repository interface](https://user-images.githubusercontent.com/9599/131272183-d2f1bb50-1ca1-42f2-936d-f23a6cbdbe13.png)

Once created, your new repository will execute a GitHub Actions workflow that uses cookiecutter to rewrite the repository to the desired state. This make take 30 seconds or so.

You can see an example of a repository generated using this template here:

- https://github.com/simonw/click-app-template-repository-demo

## Enabling workflows in your new repository

GitHub Actions like this are not allowed to create new workflows themselves.

Your new repository will have a folder in it called `.github/rename-this-to-workflows` - rename that folder to `.github/workflows` to enable the `test.yml` and `publish.yml` workflows, which can then run tests for your tool and publish new GitHub releases to PyPI, as [described here](https://github.com/simonw/click-app#publishing-your-tool-to-github).
