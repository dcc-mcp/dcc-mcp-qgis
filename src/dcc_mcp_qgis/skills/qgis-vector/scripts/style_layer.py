from dcc_mcp_core.skills_helper import run_main

from dcc_mcp_qgis.runtime import invoke


def main(
    layer_id,
    color="#38bdf8",
    outline_color="#0f172a",
    opacity=1.0,
    width=0.5,
    size=3.0,
    category_field=None,
    categories=None,
    label_field=None,
    label_size=10,
    label_color="#0f172a",
    label_buffer_size=0.7,
    label_buffer_color="#ffffff",
    font_family=None,
    label_bold=False,
):
    return invoke(
        "style_layer",
        layer_id=layer_id,
        color=color,
        outline_color=outline_color,
        opacity=opacity,
        width=width,
        size=size,
        category_field=category_field,
        categories=categories,
        label_field=label_field,
        label_size=label_size,
        label_color=label_color,
        label_buffer_size=label_buffer_size,
        label_buffer_color=label_buffer_color,
        font_family=font_family,
        label_bold=label_bold,
    )


if __name__ == "__main__":
    run_main(main)
