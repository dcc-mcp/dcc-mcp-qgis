from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(layer_id, path, format="GeoJSON"):
    return invoke("export_layer", layer_id=layer_id, path=path, format=format)


if __name__ == "__main__":
    run_main(main)
