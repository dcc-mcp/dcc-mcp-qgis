from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(layer_id, limit=25, offset=0):
    return invoke("query_features", layer_id=layer_id, limit=limit, offset=offset)


if __name__ == "__main__":
    run_main(main)
