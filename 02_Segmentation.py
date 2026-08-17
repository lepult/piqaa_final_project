# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingContext,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProject,
    QgsProcessingUtils,
)
import processing

CLASS_FIELD_NAME = "class"
SEGMENTATION_SPATIALR_PARAM = 20
SEGMENTATION_RANGER_PARAM = 15
SEGMENTATION_MINSIZE_PARAM = 50
TEXTURE_EXTRACTION_XRAD_PARAMETER = 2
TEXTURE_EXTRACTION_YRAD_PARAMETER = 2
TEXTURE_EXTRACTION_NBBIN_PARAM = 8

HARALICK_SIMPLE_MEASURES = [
    "energy",
    "entropy",
    "correlation",
    "invdiffmoment",
    "inertia",
    "clustershade",
    "clusterprominence",
    "haralickcorr",
]


def add_layer_to_load_on_completion(context, destination, layer_name):
    if not context or not destination:
        return

    details = QgsProcessingContext.LayerDetails(
        layer_name,
        context.project() if context.project() else QgsProject.instance(),
        layer_name,
    )
    context.addLayerToLoadOnCompletion(destination, details)


def run_step(alg_id, params, context, feedback):
    return processing.run(alg_id, params, context=context, feedback=feedback)


def set_stage_progress(feedback, start, end, fraction, message=None):
    """Helper to map fraction (0-1) to stage range and update progress."""
    frac = max(0.0, min(1.0, float(fraction)))
    value = start + (end - start) * frac
    feedback.setProgress(value)
    if message:
        feedback.setProgressText(message)


def compute_ndvi(input_raster, output_path, context, feedback, nir_band=4, red_band=1):
    params = {
        "INPUT_A": input_raster,
        "BAND_A": nir_band,
        "INPUT_B": input_raster,
        "BAND_B": red_band,
        "FORMULA": "(A-B)/(A+B)",
        "NO_DATA": None,
        "RTYPE": 5,
        "OUTPUT": output_path,
    }
    return run_step("gdal:rastercalculator", params, context, feedback)


def build_texture_raster_specs(raster_path, band_label, measure_names=HARALICK_SIMPLE_MEASURES):
    return [
        {"raster": raster_path, "band": i + 1, "prefix": f"{band_label}_{measure}_"}
        for i, measure in enumerate(measure_names)
    ]


def add_shape_metrics(segment_input, output_path, context, feedback):
    shape_fields = [
        ("shape_area", "$area"),
        ("shp_perimeter", "$perimeter"),
        ("shp_compactness", "(4 * pi() * $area) / ($perimeter^2)"),
    ]

    current = segment_input
    for i, (field_name, expression) in enumerate(shape_fields):
        params = {
            "INPUT": current,
            "FIELD_NAME": field_name,
            "FIELD_TYPE": 0,
            "FIELD_LENGTH": 20,
            "FIELD_PRECISION": 6,
            "FORMULA": expression,
            "OUTPUT": "TEMPORARY_OUTPUT",
        }
        result = run_step("native:fieldcalculator", params, context, feedback)
        current = result["OUTPUT"]

    save_result = run_step(
        "native:savefeatures",
        {
            "INPUT": current,
            "OUTPUT": output_path,
        },
        context,
        feedback,
    )
    return save_result["OUTPUT"]


class SegmentImage(QgsProcessingAlgorithm):
    IMAGERY = "IMAGERY"
    REFERENCE_LAYER = "REFERENCE_LAYER"
    SPATIAL_RADIUS = "SPATIAL_RADIUS"
    RANGE_RADIUS = "RANGE_RADIUS"
    MIN_SIZE = "MIN_SIZE"
    XRAD = "XRAD"
    YRAD = "YRAD"
    NBBIN = "NBBIN"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("SegmentImage", string)

    def createInstance(self):
        return SegmentImage()

    def name(self):
        return "segment_image"

    def displayName(self):
        return self.tr("03 - Segment + Metrics + Attributes")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Runs Step 03-05 in one workflow: segments imagery with OTB "
            "LargeScaleMeanShift, transfers class from reference polygons, "
            "computes Haralick textures for all channels (Red, Green, Blue, NIR), "
            "computes NDVI, and adds all zonal and shape metrics to segments."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.IMAGERY,
                self.tr("Input imagery"),
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.REFERENCE_LAYER,
                self.tr("Reference layer"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPATIAL_RADIUS,
                self.tr("Spatial radius"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=SEGMENTATION_SPATIALR_PARAM,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.RANGE_RADIUS,
                self.tr("Range radius"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=SEGMENTATION_RANGER_PARAM,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_SIZE,
                self.tr("Minimum segment size"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=SEGMENTATION_MINSIZE_PARAM,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.XRAD,
                self.tr("Texture X radius"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=TEXTURE_EXTRACTION_XRAD_PARAMETER,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.YRAD,
                self.tr("Texture Y radius"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=TEXTURE_EXTRACTION_YRAD_PARAMETER,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.NBBIN,
                self.tr("Texture number of bins"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=TEXTURE_EXTRACTION_NBBIN_PARAM,
                minValue=2,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Attributed segments"),
                QgsProcessing.TypeVectorPolygon,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        imagery_layer = self.parameterAsRasterLayer(parameters, self.IMAGERY, context)
        if imagery_layer is None:
            raise QgsProcessingException("Could not read input imagery.")

        reference_source = self.parameterAsSource(parameters, self.REFERENCE_LAYER, context)
        reference_layer = self.parameterAsVectorLayer(parameters, self.REFERENCE_LAYER, context)
        if reference_source is None or reference_layer is None:
            raise QgsProcessingException("Could not read reference layer.")

        spatialr = self.parameterAsInt(parameters, self.SPATIAL_RADIUS, context)
        ranger = self.parameterAsInt(parameters, self.RANGE_RADIUS, context)
        minsize = self.parameterAsInt(parameters, self.MIN_SIZE, context)
        xrad = self.parameterAsInt(parameters, self.XRAD, context)
        yrad = self.parameterAsInt(parameters, self.YRAD, context)
        nbbin = self.parameterAsInt(parameters, self.NBBIN, context)

        output_dest = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        if not output_dest:
            raise QgsProcessingException("Could not resolve output destination for attributed segments.")

        set_stage_progress(feedback, 0, 100, 0.0, "Initializing workflow")

        feedback.pushInfo("=== 1. Segmenting imagery ===")
        set_stage_progress(feedback, 0, 50, 0.0, "Segmenting imagery")

        # OTB can fail committing GeoPackage transactions on some setups.
        # Use an explicit Shapefile path for robust intermediate vector output.
        seg_vector_path = QgsProcessingUtils.generateTempFilename("segment_image_intermediate.shp")
        seg_raster_path = QgsProcessingUtils.generateTempFilename("segment_image_intermediate_labelmap.tif")

        seg_params = {
            "in": imagery_layer.source(),
            "spatialr": spatialr,
            "ranger": ranger,
            "minsize": minsize,
            "tilesizex": 500,
            "tilesizey": 500,
            "mode": "vector",
            "mode.vector.imfield": None,
            "mode.vector.out": seg_vector_path,
            "mode.raster.out": seg_raster_path,
            "cleanup": True,
            "outputpixeltype": 5,
        }

        seg_result = run_step(
            "otb:LargeScaleMeanShift",
            seg_params,
            context,
            feedback,
        )

        seg_output = seg_result.get("mode.vector.out") or seg_result.get("OUTPUT")
        if not seg_output:
            raise QgsProcessingException("Segmentation output is missing.")

        set_stage_progress(feedback, 50, 55, 0.0, "Segmentation complete, transferring class labels")

        feedback.pushInfo("=== 2. Transferring class labels ===")

        label_params = {
            "INPUT": seg_output,
            "PREDICATE": [0],
            "JOIN": reference_layer,
            "JOIN_FIELDS": [CLASS_FIELD_NAME],
            "METHOD": 2,
            "DISCARD_NONMATCHING": False,
            "PREFIX": "",
            "OUTPUT": output_dest,
        }

        label_result = run_step(
            "native:joinattributesbylocation",
            label_params,
            context,
            feedback,
        )

        current_input = label_result["OUTPUT"]

        set_stage_progress(feedback, 55, 65, 0.0, "Computing texture rasters")

        feedback.pushInfo("=== 3. Computing texture rasters (all channels) ===")

        texture_channels = [
            ("red", 1),
            ("green", 2),
            ("blue", 3),
            ("nir", 4),
        ]

        texture_outputs = {}
        total_channels = len(texture_channels)
        for i, (channel_name, channel_num) in enumerate(texture_channels, 1):
            tex_out = QgsProcessingUtils.generateTempFilename(
                f"texture_{channel_name}.tif"
            )
            tex_params = {
                "in": imagery_layer.source(),
                "channel": channel_num,
                "step": 1,
                "parameters.xrad": xrad,
                "parameters.yrad": yrad,
                "parameters.xoff": 1,
                "parameters.yoff": 1,
                "parameters.min": 0,
                "parameters.max": 255,
                "parameters.nbbin": nbbin,
                "texture": "simple",
                "out": tex_out,
            }
            run_step("otb:HaralickTextureExtraction", tex_params, context, feedback)
            texture_outputs[channel_name] = tex_out
            set_stage_progress(
                feedback,
                55,
                65,
                i / total_channels,
                f"Texture extraction ({i}/{total_channels}): {channel_name}",
            )

        set_stage_progress(feedback, 65, 70, 0.0, "Computing NDVI")

        feedback.pushInfo("=== 4. Computing NDVI ===")

        ndvi_path = QgsProcessingUtils.generateTempFilename("ndvi.tif")
        compute_ndvi(
            input_raster=imagery_layer.source(),
            output_path=ndvi_path,
            context=context,
            feedback=feedback,
        )

        set_stage_progress(feedback, 70, 95, 0.0, "Adding zonal metrics to segments")

        feedback.pushInfo("=== 5. Adding zonal metrics to segments ===")

        raster_specs = []
        for band_label, raster_path in texture_outputs.items():
            raster_specs.extend(build_texture_raster_specs(raster_path, band_label))

        raster_specs.append({"raster": ndvi_path, "band": 1, "prefix": "ndvi_"})
        raster_specs.extend(
            [
                {"raster": imagery_layer.source(), "band": 1, "prefix": "red_"},
                {"raster": imagery_layer.source(), "band": 2, "prefix": "green_"},
                {"raster": imagery_layer.source(), "band": 3, "prefix": "blue_"},
                {"raster": imagery_layer.source(), "band": 4, "prefix": "nir_"},
            ]
        )

        total_rasters = len(raster_specs)
        for i, spec in enumerate(raster_specs, 1):
            params = {
                "INPUT": current_input,
                "INPUT_RASTER": spec["raster"],
                "RASTER_BAND": spec["band"],
                "COLUMN_PREFIX": spec["prefix"],
                "STATISTICS": [2],
                "OUTPUT": "TEMPORARY_OUTPUT",
            }
            result = run_step("native:zonalstatisticsfb", params, context, feedback)
            current_input = result["OUTPUT"]
            set_stage_progress(
                feedback,
                70,
                95,
                i / total_rasters,
                f"Zonal stats ({i}/{total_rasters}): {spec['prefix']}",
            )

        set_stage_progress(feedback, 95, 100, 0.0, "Adding shape metrics")

        feedback.pushInfo("=== 6. Adding shape metrics ===")

        final_output = add_shape_metrics(
            current_input,
            output_dest,
            context=context,
            feedback=feedback,
        )

        set_stage_progress(feedback, 95, 100, 1.0, "Workflow complete")

        add_layer_to_load_on_completion(context, final_output, "Attributed segments")

        return {
            self.OUTPUT: final_output,
        }
