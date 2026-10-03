from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(layer_id, feature_id, attributes=None, wkt=None):
    return invoke("update_feature", layer_id=layer_id, feature_id=feature_id, attributes=attributes, wkt=wkt)


if __name__ == "__main__":
    run_main(main)
