from parameters import TEXTURE_EXTRACTION_XRAD_PARAMETER, TEXTURE_EXTRACTION_YRAD_PARAMETER, TEXTURE_EXTRACTION_NBBIN_PARAM
from constants import PROJECT_PATH, AOI_IMAGERY_NAME, DEFAULT_BAND_NAMES, DERIVED_INDICES_GROUP_NAME
from helper import log
from helper import run_geobia_step

def run_haralick_all_bands(
    input_raster,
    output_dir,
    band_names=DEFAULT_BAND_NAMES,
    group_name=DERIVED_INDICES_GROUP_NAME,
    step=1,
    xrad=TEXTURE_EXTRACTION_XRAD_PARAMETER,
    yrad=TEXTURE_EXTRACTION_YRAD_PARAMETER,
    xoff=1,
    yoff=1,
    pixel_min=0,
    pixel_max=255,
    nbbin=TEXTURE_EXTRACTION_NBBIN_PARAM,
    texture='simple',
):
    """
    Runs otb:HaralickTextureExtraction once per band (channel 1-4) on
    input_raster, saves each output into output_dir, and adds each
    result to a dedicated layer group in the current QGIS project.
 
    band_names order must match the actual band order of input_raster
    (default assumes band 1=red, 2=green, 3=blue, 4=nir).
 
    Returns a dict: {band_name: {'params': ..., 'result': ..., 'path': ...}}
    """
    if len(band_names) != 4:
        raise ValueError("band_names must have exactly 4 entries (one per channel 1-4)")
 
    # --- Set up (or find) the destination layer group ---
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.insertGroup(0, group_name)
        log(f"Created layer group: {group_name}")
    else:
        log(f"Using existing layer group: {group_name}")
 
    outputs = {}
 
    for channel, band_name in enumerate(band_names, start=1):
        step_name = f"GLCM texture extraction ({band_name} band, channel {channel})"
        out_path = f'{output_dir}/{get_output_file_name(band_name=band_name)}'
 
        params = {
            'in': input_raster,
            'channel': channel,
            'step': step,
            'parameters.xrad': xrad,
            'parameters.yrad': yrad,
            'parameters.xoff': xoff,
            'parameters.yoff': yoff,
            'parameters.min': pixel_min,
            'parameters.max': pixel_max,
            'parameters.nbbin': nbbin,
            'texture': texture,
            'out': out_path,
        }
 
        result = run_geobia_step('otb:HaralickTextureExtraction', params, step_name)
        outputs[band_name] = {'params': params, 'result': result, 'path': out_path}
 
        # --- Load the output raster and add it to the group ---
        raster_layer = QgsRasterLayer(out_path, f'haralick_{band_name}')
        if not raster_layer.isValid():
            log(f"WARNING: output raster failed to load: {out_path}", Qgis.MessageLevel.Warning)
            continue
 
        QgsProject.instance().addMapLayer(raster_layer, False)  # False = don't add to root/legend directly
        group.addLayer(raster_layer)
        log(f"Added layer 'haralick_{band_name}' to group '{group_name}'")
 
    iface.messageBar().pushSuccess("GEOBIA", f"Haralick texture extraction complete for {len(band_names)} bands.")
    return outputs

def get_output_file_name(
    band_name,
    band_number=None,
    band_names=DEFAULT_BAND_NAMES,
):
    if (band_number != None):
        return f'textures_{DEFAULT_BAND_NAMES[band_number]}_band.tif'

    return f'textures_{band_name}_band.tif'
 

# --- Run it ---
haralick_outputs = run_haralick_all_bands(
    input_raster=f'{PROJECT_PATH}/{AOI_IMAGERY_NAME}',
    output_dir=PROJECT_PATH,
)