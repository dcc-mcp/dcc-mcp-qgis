from dcc_mcp_core.skills_helper import run_main, skill_success

from dcc_mcp_qgis.runtime import CAPABILITIES


def main():
    return skill_success("QGIS capabilities", **CAPABILITIES)


if __name__ == "__main__":
    run_main(main)
