from constants import NDVI_OUTPUT_FILE_NAME, PROJECT_PATH, ZONAL_STATISTICS_OUTPUT_FILE_NAME, LABELED_FILE_NAME, LABELED_TABLE_NAME

HARALICK_SIMPLE_MEASURES = [
    'energy',
    'entropy',
    'correlation',
    'invdiffmoment',
    'inertia',
    'clustershade',
    'clusterprominence',
    'haralickcorr',
]
 
 
def build_texture_raster_specs(raster_path, band_label, measure_names=HARALICK_SIMPLE_MEASURES):
    """
    Builds the list of {'raster', 'band', 'prefix'} specs for all 8
    Haralick measure bands of one texture raster (e.g. the red-band
    texture output), so each ends up with a readable column name
    like red_entropy_ instead of red_band4_.
    """
    return [
        {'raster': raster_path, 'band': i + 1, 'prefix': f'{band_label}_{measure}_'}
        for i, measure in enumerate(measure_names)
    ]
 
 
def run_zonal_statistics_pipeline(segment_input, raster_band_specs, final_output_path):
    """
    Repeatedly runs native:zonalstatisticsfb, once per raster/band
    combination in raster_band_specs, chaining each step's output
    into the next step's input — exactly matching the manual
    "repeat once per raster/band, ending with one layer with all
    attributes" workflow described in the documentation.
 
    raster_band_specs: list of dicts, each with:
        'raster' : path to the raster (or 'raster|layername=...' string)
        'band'   : raster band number (1-indexed)
        'prefix' : output column prefix, e.g. 'red_entropy_'
 
    final_output_path: where the last step writes its result
        (e.g. a .gpkg path). Intermediate steps use TEMPORARY_OUTPUT.
 
    Returns the final output (path or layer, as returned by the
    last processing.run() call).
    """
    current_input = segment_input
 
    for i, spec in enumerate(raster_band_specs):
        is_last = (i == len(raster_band_specs) - 1)
        output = final_output_path if is_last else 'TEMPORARY_OUTPUT'
 
        params = {
            'INPUT': current_input,
            'INPUT_RASTER': spec['raster'],
            'RASTER_BAND': spec['band'],
            'COLUMN_PREFIX': spec['prefix'],
            'STATISTICS': [2],  # 2 = Mean only (matches --STATISTICS=2 in the CLI example).
                                 # Python API expects a list even for a single statistic.
            'OUTPUT': output,
        }
 
        step_name = f"Zonal stats: {spec['prefix']} (raster band {spec['band']})"
        result = run_geobia_step('native:zonalstatisticsfb', params, step_name)
        current_input = result['OUTPUT']
 
    iface.messageBar().pushSuccess("GEOBIA", "Zonal statistics complete — all attributes attached.")
    return current_input
 
 
# --- Build the full list of raster/band combinations to attach ---
# NOTE: distance/area units and ellipsoid are qgis_process CLI-level
# settings tied to project measurement configuration, not parameters
# of native:zonalstatisticsfb itself — they aren't needed in the
# params dict when calling processing.run() from a script.
 
zonal_specs = []
 
# Texture rasters: 8 Haralick measure bands each
zonal_specs += build_texture_raster_specs(haralick_outputs['red']['path'], 'red')
zonal_specs += build_texture_raster_specs(haralick_outputs['green']['path'], 'green')
zonal_specs += build_texture_raster_specs(haralick_outputs['blue']['path'], 'blue')
zonal_specs += build_texture_raster_specs(haralick_outputs['nir']['path'], 'nir')
 
# NDVI: single band
zonal_specs.append({'raster': f'{PROJECT_PATH}/{NDVI_OUTPUT_FILE_NAME}, 'band': 1, 'prefix': 'ndvi_'})
 
# Spectral bands from the original imagery
SPECTRAL_IMAGE_PATH = f'{PROJECT_PATH}/{AOI_IMAGERY_NAME}'  # <-- adjust if this differs from your segmentation input
zonal_specs += [
    {'raster': SPECTRAL_IMAGE_PATH, 'band': 1, 'prefix': 'red_'},
    {'raster': SPECTRAL_IMAGE_PATH, 'band': 2, 'prefix': 'green_'},
    {'raster': SPECTRAL_IMAGE_PATH, 'band': 3, 'prefix': 'blue_'},
    {'raster': SPECTRAL_IMAGE_PATH, 'band': 4, 'prefix': 'nir_'},
]
 
# --- Run the chained zonal statistics pipeline ---
ZONAL_OUTPUT_PATH = f'{PROJECT_PATH}/{ZONAL_STATISTICS_OUTPUT_FILE_NAME}'
 
final_attributed_layer = run_zonal_statistics_pipeline(
    segment_input=f'{PROJECT_PATH}/{LABELED_FILE_NAME}|layername={LABELED_TABLE_NAME}',
    raster_band_specs=zonal_specs,
    final_output_path=ZONAL_OUTPUT_PATH,
)
