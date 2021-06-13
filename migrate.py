import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, MutableMapping, Optional

import click
import requirements
import toml
from requirements.requirement import Requirement

PREVIOUS_SAFETY_COMMAND = '"poetry export --dev --without-hashes -f requirements.txt | safety check --full-report --stdin"'
NEW_SAFETY_COMMAND = '"poetry export --dev --without-hashes -f requirements.txt | safety check --full-report --stdin"'

PREVIOUS_TIME_COMMAND = (
    '{ { time eval "$cmd" >>"$stdout" 2>&1 ; } >>"$timer" 2>&1 ; } &'
)
NEW_TIME_COMMAND = '{ { time eval "$cmd" >>"$stdout" 2>&1 ; } >>"$timer" 2>&1 ; } &'


package_hash_re = re.compile(r"\-\-hash=sha256:[0-9a-f]{64}")
version_re = re.compile(r"version=\"(?P<version>.*)\"", re.MULTILINE)
description_re = re.compile(r"description=\"(?P<description>.*)\"", re.MULTILINE)
new_line_description_re = re.compile(
    r"description=\(.*\n\s*\"(?P<description>.*)\"\n.*\)", re.MULTILINE
)
author_re = re.compile(r"author=\"(?P<author>.*)\"", re.MULTILINE)
author_email_re = re.compile(r"author_email=\"(?P<author_email>.*)\"", re.MULTILINE)
url_re = re.compile(r"url=\"(?P<url>.*)\"", re.MULTILINE)
python_requires_re = re.compile(
    r"python_requires=\"(?P<python_requires>.*)\"", re.MULTILINE
)
console_scripts_re = re.compile(
    r"\"(?P<cli>[\w_]+)\s+=\s+(?P<package>.+:.+)\"", re.MULTILINE
)


def get_description(setup: str) -> Optional[str]:
    for description in description_re.finditer(setup):
        return description.groupdict()["description"]

    new_line_description = new_line_description_re.findall(setup)

    return new_line_description[0] if new_line_description else ""


def add_poetry_section(
    package_path: Path,
    pyproject: MutableMapping,
    setup: str,
    namespace: Optional[str],
) -> MutableMapping:
    poetry = pyproject.setdefault("tool", {}).setdefault("poetry", {})
    poetry["name"] = package_path.stem.replace("_", "-")
    poetry["description"] = get_description(setup)
    poetry["authors"] = [
        author_re.findall(setup)[0] + " <" + author_email_re.findall(setup)[0] + ">"
    ]
    poetry["readme"] = "README.md"
    poetry["repository"] = url_re.findall(setup)[0]
    poetry["version"] = version_re.findall(setup)[0]

    if namespace:
        poetry["packages"] = [{"include": namespace}]

    return pyproject


def add_requirement_section(
    pyproject: MutableMapping, requirements: Iterable, dev: bool
) -> MutableMapping:
    section = ("dev-" if dev else "") + "dependencies"
    dependencies = (
        pyproject.setdefault("tool", {})
        .setdefault("poetry", {})
        .setdefault(section, {})
    )

    for requirement in requirements:
        # Editable package
        if requirement.editable:
            specs = {"path": requirement.path[5:].strip(), "develop": True}

            if dev:
                specs["extras"] = ["dev"]

        # Single version spec
        elif len(requirement.specs) == 1:
            specs = "^" + requirement.specs[0][1]

        # No specs
        elif len(requirement.specs) == 0:
            raise NotImplementedError

        # Anything else
        else:
            raise NotImplementedError

        # Has extra requirements
        if requirement.extras:
            if not isinstance(specs, dict):
                specs = {"version": specs}

            specs["extras"] = requirement.extras

        # Write spec
        dependencies[requirement.name] = specs

    return pyproject


def get_python_version(setup: str) -> str:
    python_requires = python_requires_re.findall(setup)

    if not python_requires:
        return "^3.9"

    return python_requires[0].replace(">=", "^")


def add_python_version(pyproject: MutableMapping, setup: str) -> MutableMapping:
    dependencies = (
        pyproject.setdefault("tool", {})
        .setdefault("poetry", {})
        .setdefault("dependencies", {})
    )
    dependencies["python"] = get_python_version(setup)

    return pyproject


def get_requirement_name(requirement: Requirement) -> str:
    if requirement.name is None:
        name = Path(requirement.path).stem.replace("[dev]", "")
    else:
        name = requirement.name

    name = name.replace("_", "-")

    return name


def load_requirements(package_path: Path, requirement_filename: str) -> Iterable:
    requirements_in = list(
        requirements.parse((package_path / f"{requirement_filename}.in").open())
    )

    # Strips the --hash:... blocks because not supported by requirements-parse
    requirements_txt_raw = (package_path / f"{requirement_filename}.txt").read_text()
    requirements_txt_raw = package_hash_re.sub("", requirements_txt_raw)
    requirements_txt_raw = requirements_txt_raw.replace("\\", "")
    requirements_txt = list(requirements.parse(requirements_txt_raw))

    missing_names = [
        requirement for requirement in requirements_in if requirement.name is None
    ]

    if missing_names:
        raise ValueError(
            "In {}.in missing egg= for this packages: {}".format(
                requirement_filename, missing_names
            )
        )

    requirements_in_map = {
        requirement.name.replace("_", "-"): requirement
        for requirement in requirements_in
    }
    requirements_txt_map = {
        requirement.name.replace("_", "-"): requirement
        for requirement in requirements_txt
    }

    if None in requirements_in_map or None in requirements_txt_map:
        raise ValueError("At least one editable requirement without egg=<name>")

    return (
        requirements_txt_map[requirement_in]
        for requirement_in in requirements_in_map
        if requirement_in != "pip-tools"
    )


def add_build_system(pyproject: MutableMapping) -> MutableMapping:
    build_system = pyproject.setdefault("build-system", {})
    build_system["requires"] = ["poetry-core>=1.0.0"]
    build_system["build-backend"] = "poetry.core.masonry.api"

    return pyproject


def add_scripts(pyproject: MutableMapping, setup: str) -> MutableMapping:
    matches = (match.groupdict() for match in console_scripts_re.finditer(setup))
    console_scripts = {match["cli"]: match["package"] for match in matches}

    if console_scripts:
        scripts = (
            pyproject.setdefault("tool", {})
            .setdefault("poetry", {})
            .setdefault("scripts", {})
        )
        scripts.update(console_scripts)

    return pyproject


def add_private_repo(pyproject: MutableMapping, private_repo: str) -> MutableMapping:
    name, url = private_repo.split(":", maxsplit=1)

    sources = (
        pyproject.setdefault("tool", {}).setdefault("poetry").setdefault("source", [])
    )

    for source in sources:
        if source["name"] == name:
            source["url"] = url

            return pyproject

    sources.append({"name": name, "url": url})

    return pyproject


def update_pyproject(
    package_path: Path, namespace: Optional[str], private_repo: Optional[str]
):
    setup_path = package_path / "setup.py"

    if not setup_path.exists():
        return

    setup = setup_path.read_text()
    pyproject_path = package_path / "pyproject.toml"
    requirements = load_requirements(package_path, "requirements")
    requirements_dev = load_requirements(package_path, "requirements-dev")

    pyproject = toml.load(pyproject_path.open())
    pyproject = add_poetry_section(package_path, pyproject, setup, namespace)
    pyproject = add_python_version(pyproject, setup)
    pyproject = add_build_system(pyproject)
    pyproject = add_requirement_section(pyproject, requirements, False)
    pyproject = add_requirement_section(pyproject, requirements_dev, True)
    pyproject = add_scripts(pyproject, setup)

    if private_repo:
        pyproject = add_private_repo(pyproject, private_repo)

    toml.dump(pyproject, pyproject_path.open("w"))


def remove_requirements(package_path: Path):
    for requirement in package_path.glob("requirements*"):
        requirement.unlink()


def remove_setup(package_path: Path):
    (package_path / "setup.py").unlink(missing_ok=True)


def check_dependencies(package_path: Path):
    env = dict(os.environ)
    env.pop("POETRY", None)
    env.pop("VIRTUAL_ENV", None)

    subprocess.check_call(["poetry", "lock"], cwd=package_path, env=env)
    subprocess.check_call(
        ["poetry", "install", "--remove-untracked"], cwd=package_path, env=env
    )


def update_safety_check(package_path: Path):
    check_path = package_path / "bin" / "check"

    check = check_path.read_text()
    check = check.replace(PREVIOUS_SAFETY_COMMAND, NEW_SAFETY_COMMAND)
    check = check.replace(PREVIOUS_TIME_COMMAND, NEW_TIME_COMMAND)
    check_path.write_text(check)


def migrate(
    package_path: Path,
    namespace: Optional[str],
    delete: bool,
    private_repo: Optional[str],
):
    update_pyproject(package_path, namespace, private_repo)
    check_dependencies(package_path)

    update_safety_check(package_path)

    if delete:
        remove_requirements(package_path)
        remove_setup(package_path)


@click.command()
@click.argument(
    "package_path",
    type=click.Path(exists=True, file_okay=False, writable=True, path_type=Path),
)
@click.option("--namespace")
@click.option(
    "--private-repo", help="An optional private repository in the form of <name>:<url>"
)
@click.option("-D", "--delete", is_flag=True)
def main(
    package_path: Path,
    namespace: Optional[str],
    delete: bool,
    private_repo: Optional[str],
):
    migrate(package_path, namespace, delete, private_repo)


if __name__ == "__main__":
    main()
