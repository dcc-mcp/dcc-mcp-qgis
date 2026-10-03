from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(path, discard_changes=False):
    return invoke("reopen_project", path=path, discard_changes=discard_changes)


if __name__ == "__main__":
    run_main(main)
