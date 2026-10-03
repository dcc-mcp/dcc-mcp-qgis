from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(path, width=800, height=600):
    return invoke("render_map", path=path, width=width, height=height)


if __name__ == "__main__":
    run_main(main)
