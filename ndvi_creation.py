from helper import run_geobia_step

def compute_ndvi(
    input_raster,
    output_path,
    nir_band=4,
    red_band=1,
    context=None,
    feedback=None,
):
    """
    Computes NDVI = (NIR - Red) / (NIR + Red) from a single multiband raster.
    Returns the processing result dict from gdal:rastercalculator.
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
 
    return run_geobia_step(
        'gdal:rastercalculator',
        params,
        "NDVI computation",
        context=context,
        feedback=feedback,
    )
