from constants import NDVI_OUTPUT_FILE_NAME, PROJECT_PATH, AOI_IMAGERY_NAME, DERIVED_INDICES_GROUP_NAME

def compute_ndvi(
    input_raster,
    output_path,
    nir_band=4,
    red_band=1,
    group_name=DERIVED_INDICES_GROUP_NAME,
    layer_name='ndvi',
):
    """
    Computes NDVI = (NIR - Red) / (NIR + Red) from a single multiband
    raster using GDAL's raster calculator, without requiring the input
    to already be loaded as a named layer in the project (unlike the
    QGIS Raster Calculator's "layer@band" syntax, this works directly
    off band indices in the file, which is more robust for scripting).
 
    Adds the result to a dedicated layer group in the current project.
 
    Returns the processing result dict.
    """
    params = {
        'INPUT_A': input_raster,
        'BAND_A': nir_band,
        'INPUT_B': input_raster,
        'BAND_B': red_band,
        'FORMULA': '(A-B)/(A+B)',
        'NO_DATA': None,
        'RTYPE': 5,  # Float32 — NDVI is a ratio in [-1, 1], needs float precision
        'OUTPUT': output_path,
    }
 
    result = run_geobia_step('gdal:rastercalculator', params, "NDVI computation")
 
    # --- Load the output raster and add it to a group ---
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.insertGroup(0, group_name)
        log(f"Created layer group: {group_name}")
 
    raster_layer = QgsRasterLayer(output_path, layer_name)
    if not raster_layer.isValid():
        log(f"WARNING: NDVI output raster failed to load: {output_path}", Qgis.MessageLevel.Warning)
    else:
        QgsProject.instance().addMapLayer(raster_layer, False)
        group.addLayer(raster_layer)
        log(f"Added layer '{layer_name}' to group '{group_name}'")
 
    iface.messageBar().pushSuccess("GEOBIA", "NDVI computation complete.")
    return result
 
 
# --- Run it ---
NDVI_INPUT_IMAGE = f'{PROJECT_PATH}/aoi_test_small.tif'  # <-- adjust to your actual 4-band raster
NDVI_OUTPUT_PATH = f'{PROJECT_PATH}/{NDVI_OUTPUT_FILE_NAME}'
 
ndvi_result = compute_ndvi(
    input_raster=f'{PROJECT_PATH}/{AOI_IMAGERY_NAME}',
    output_path=NDVI_OUTPUT_PATH,
    nir_band=4,
    red_band=1,
)
