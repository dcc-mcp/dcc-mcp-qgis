from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main():
    return invoke("status")


if __name__ == "__main__":
    run_main(main)
