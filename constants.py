PROJECT_PATH = 'D:/IFGI/AOHRSI/clean'

AOI_IMAGERY_NAME = 'aoi_test_small.tif'
SEGMENTED_FILE_NAME = 'aoi_segmented_imagery2.gpkg'
SEGMENTED_LAYER_NAME = 'aoi_segmented_imagery2'

CLASS_POLYGON_FILE = f'{PROJECT_PATH}/greenhouses_polygon.gpkg'
CLASS_POLYGON_LAYER = 'greenhouses_non_greenhouses_polygons'

LABELED_FILE_NAME = 'aoi_segmented_labeled_test.gpkg'
LABELED_TABLE_NAME = 'aoi_segmented_labeled_test'

CLASS_FIELD_NAME = 'class'

DEFAULT_BAND_NAMES = ('red', 'green', 'blue', 'nir');

DERIVED_INDICES_GROUP_NAME = 'derived_indices'

ZONAL_STATISTICS_OUTPUT_FILE_NAME = 'aoi_segments_with_zonal_statistics_attributes.gpkg'
ZONAL_STATISTICS_LAYER_NAME = 'aoi_segments_with_zonal_statistics_attributes'

LOG_TAG = "GEOBIA"

NDVI_OUTPUT_FILE_NAME = 'ndvi.tif'

RANDOM_FOREST_READY_SEGMENTS_FILE_NAME = 'aoi_segments_ready_for_rf'