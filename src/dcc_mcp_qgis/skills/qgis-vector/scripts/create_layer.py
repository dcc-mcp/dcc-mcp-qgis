from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(name, geometry_type, crs="EPSG:3857", fields=None):
    return invoke("create_layer", name=name, geometry_type=geometry_type, crs=crs, fields=fields)


if __name__ == "__main__":
    run_main(main)
