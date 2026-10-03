from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(layer_id, features):
    return invoke("add_features", layer_id=layer_id, features=features)


if __name__ == "__main__":
    run_main(main)
