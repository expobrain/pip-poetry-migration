# poetry-migration

Tool to migrate a Pip/Pip-Tools package or project into Poetry.

This code converts a `setup.py` into a Poetry installation, created the `poetry.lock` file and installs the packages to ensure that they are fully compatible.

Optionally deletes the unnecessary files like the `requirements*` files and the `bin/*` scripts not needed anymore.

> Note: This code is not supposed to survive after the migraton so unit test are absent and code quality is bare minimum.

# Setup

Run:

```shell
poetry install
```

to setup the environment.

# Migration

## Migrate a project/package

Run:

```shell
poetry run python migrate.py \
    --private-repo "<private_repo_name>:<private_repo_url>" \
    <path/to/setup.py>
```

to migrate your codebase to Poetry.

This operation is idempotent and can be run multiple times.

If you want to remove the unnecessary files, pass the `-D` option.

## Migrate namespaced package

Namespaced packages needs a rot namespace to be defined:

```shell
poetry run python migrate.py \
    --namespace <root_namespace_name>
    <path/to/setup.py>
```

# Caveats

- the `poetry.toml` file is not well formatted after the conversion
- CLI tool can fail for some configurations
