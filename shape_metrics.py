from constants import PROJECT_PATH, ZONAL_STATISTICS_OUTPUT_FILE_NAME, RANDOM_FOREST_READY_SEGMENTS_FILE_NAME
from helper import run_geobia_step

SHAPE_FIELDS = [
    ('shape_area', '$area'),
    ('shp_perimeter', '$perimeter'),
    ('shp_compactness', '(4 * pi() * $area) / ($perimeter^2)'),
]

SHAPE_METRICS_OUTPUT_FILE_NAME = 'aoi_segments_with_shape_metrics.gpkg'


def add_shape_metrics(segment_input, output_path, fields=SHAPE_FIELDS):
    """Chains Field Calculator once per shape field, writing only the last step to disk."""
    current = segment_input
    for i, (field_name, expression) in enumerate(fields):
        is_last = (i == len(fields) - 1)
        params = {
            'INPUT': current,
            'FIELD_NAME': field_name,
            'FIELD_TYPE': 0,  # Float
            'FIELD_LENGTH': 20,
            'FIELD_PRECISION': 6,
            'FORMULA': expression,
            'OUTPUT': output_path if is_last else 'TEMPORARY_OUTPUT',
        }
        result = run_geobia_step('native:fieldcalculator', params, f"Shape metric: {field_name}")
        current = result['OUTPUT']
    return current


add_shape_metrics(
    segment_input=f'{PROJECT_PATH}/{ZONAL_STATISTICS_OUTPUT_FILE_NAME}|layername=aoi_segments_with_zonal_statistics_attributes',
    output_path=f'{PROJECT_PATH}/{RANDOM_FOREST_READY_SEGMENTS_FILE_NAME}',
)
