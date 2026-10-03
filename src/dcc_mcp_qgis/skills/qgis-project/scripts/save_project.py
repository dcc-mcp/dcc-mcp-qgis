from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(directory):
    return invoke("save_project", directory=directory)


if __name__ == "__main__":
    run_main(main)
