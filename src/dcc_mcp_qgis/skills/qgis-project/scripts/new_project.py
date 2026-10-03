from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(title="Untitled", crs="EPSG:3857", discard_changes=False):
    return invoke("new_project", title=title, crs=crs, discard_changes=discard_changes)


if __name__ == "__main__":
    run_main(main)
