#!/bin/env python3

from grp import getgrall
from logging import (
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    CRITICAL,
    basicConfig,
    getLogger,
    Formatter,
    StreamHandler,
)
from argparse import ArgumentParser, Namespace
from platform import freedesktop_os_release
from os import chdir, environ, makedirs
from os.path import exists, expandvars, join, basename, dirname
from re import compile
from subprocess import run, CalledProcessError
from sys import argv

from yaml import SafeLoader, load

log = getLogger()
basicConfig(format="%(levelname)s %(message)s (%(filename)s:%(lineno)d)", level=INFO)


def get_context(filename: str) -> dict:
    """Read and enrich YAML with environment variables

    Args:
        filename (str): YAML file to load

    Returns:
        dict: parsed YAML context
    """

    pattern = compile(r".*\$\{([^}^{]+)\}.*")

    def expander(loader, node):
        return expandvars(node.value)

    class EnvLoader(SafeLoader):
        pass

    EnvLoader.add_implicit_resolver("!path", pattern, None)
    EnvLoader.add_constructor("!path", expander)

    with open(filename) as f:
        return load(f, Loader=EnvLoader)


def on_flatpak(context: dict) -> None:
    """Handle flatpak remotes and apps

    Args:
        context (dict): list of remotes to enable and list of apps to install
    """

    for remote in context.get("remotes", []):
        run(
            f"flatpak remote-add --if-not-exists {remote['name']} {remote['url']}",
            check=True,
            shell=True,
        )
    for app in context.get("apps", []):
        run(f"flatpak install -y {app}", check=True, shell=True)


def on_copr(context: list) -> None:
    """COPR repositores

    Args:
        context (list): list of COPR repos to enable
    """
    for name in context:
        run(f"sudo dnf copr enable {name}", check=True, shell=True)


def on_packages(context: list) -> None:
    """Packages to install

    Args:
        context (list): List of packages (can include URLs for dnf/apt to fetch)
    """
    distro = freedesktop_os_release()["ID"]
    packages = " ".join(context)
    if distro == "fedora":
        run(f"sudo dnf install -y {packages}", check=True, shell=True)
    elif distro in ["ubuntu", "debian"]:
        run(f"sudo apt install -y {packages}", check=True, shell=True)
    else:
        log.error(f"Cannot determine how to install packages in {distro}, exiting")
        exit(-1)


def on_runcmd(context: list) -> None:
    """Shell Commands

    Args:
        context (list): List of shell commands to execute
    """
    for cmd in context:
        log.info(cmd)
        run(cmd, check=False, shell=True)


def on_groups(context: dict) -> None:
    """Groups to add users to

    Args:
        context (dict): group and users to add. If users has blanks, we assume it's a list of users.
    """
    for group, users in context.items():
        if " " in users:
            users = users.split()
        else:
            users = [users]
        for user in users:
            cmd = f"sudo usermod -aG {group} {user}"
            log.warning(cmd)
            run(cmd, check=True, shell=True)


def on_package_upgrade(context: bool) -> None:
    """Package Upgrade

    Args:
        context (boolean):
    """
    if not context:
        return
    distro = freedesktop_os_release()["ID"]
    if distro == "fedora":
        run(f"sudo dnf update -y", check=True, shell=True)
    elif distro in ["ubuntu", "debian"]:
        run(f"sudo apt update && sudo apt dist-upgrade -y", check=True, shell=True)
    else:
        log.error(f"Cannot determine how to upgrade packages in {distro}, exiting")
        exit(-1)


def on_write_files(context: list) -> None:
    """Write files

    Args:
        context (list): List of file specifications (path, append, content) to write.
    """
    for file in context:
        base = dirname(file["path"])
        try:
            if not exists(base):
                log.warning(f"--> Creating {base}")
                makedirs(base)
            if file.get("append", false):
                mode = "wa"
            else:
                mode = "w"
            with open(file["path"], mode) as h:
                h.write(file["content"])
        except Exception as e:
            log.error(e)
            exit(-1)


def on_build(context: list) -> None:
    """Repositories to build locally

    Args:
        context (list): List of repositories to clone locally and commands to execute inside them.
    """
    path = context.get("root", expandvars("${HOME}/tmp/build"))
    if not exists(path):
        log.warning(f"--> Creating {path}")
        makedirs(path)
    repos = context.get("repositories", [])
    for repo in repos:
        url = repo.get("url", "")
        checkout_path = join(path, basename(url))
        try:
            if url:
                if exists(checkout_path):
                    log.info(f"Updating {url}")
                    run(f"git pull", check=True, shell=True, cwd=checkout_path)
                else:
                    log.info(f"Cloning {url}")
                    run(f"git clone {repo['url']}", check=True, shell=True, cwd=path)
                commands = repo.get("commands", [])
                for item in commands:
                    log.info(item)
                    run(item, check=True, shell=True, cwd=checkout_path)
        except CalledProcessError as e:
            log.error(e)
            exit(-1)


def main(args: Namespace) -> None:
    actions = get_context(args.filename)
    steps = actions.keys()
    if args.steps:
        steps = filter(lambda x: x in args.steps, actions.keys())
    for step in steps:
        if step in actions.keys():
            name = f"on_{step}"
            if name in globals():
                globals()[name](actions[step])


if __name__ == "__main__":
    p = ArgumentParser("Ground-init provisioning script")
    p.add_argument("--steps", type=str, nargs="+", help="list of steps to execute")
    p.add_argument("filename", type=str, help="YAML file")
    args = p.parse_args()
    main(args)
