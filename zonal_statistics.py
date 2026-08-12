# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProject,
    QgsProcessingParameterRasterLayer,
)
import processing

def run_step(alg_id, params, context, feedback):
    return processing.run(alg_id, params, context=context, feedback=feedback)


def add_layer_to_load_on_completion(context, destination, layer_name):
    if not context or not destination:
        return

    details = QgsProcessingContext.LayerDetails(
        layer_name,
        context.project() if context.project() else QgsProject.instance(),
        layer_name,
    )
    context.addLayerToLoadOnCompletion(destination, details)


def add_shape_metrics(segment_input, output_path, context, feedback):
    shape_fields = [
        ("shape_area", "$area"),
        ("shp_perimeter", "$perimeter"),
        ("shp_compactness", "(4 * pi() * $area) / ($perimeter^2)"),
    ]

    current = segment_input
    for i, (field_name, expression) in enumerate(shape_fields):
        is_last = i == len(shape_fields) - 1
        params = {
            "INPUT": current,
            "FIELD_NAME": field_name,
            "FIELD_TYPE": 0,
            "FIELD_LENGTH": 20,
            "FIELD_PRECISION": 6,
            "FORMULA": expression,
            "OUTPUT": output_path if is_last else "TEMPORARY_OUTPUT",
        }
        result = run_step("native:fieldcalculator", params, context, feedback)
        current = result["OUTPUT"]

    return current

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


def build_texture_raster_specs(raster_path, band_label, measure_names=HARALICK_SIMPLE_MEASURES):
    return [
        {"raster": raster_path, "band": i + 1, "prefix": f"{band_label}_{measure}_"}
        for i, measure in enumerate(measure_names)
    ]


class AddAttributesToSegments(QgsProcessingAlgorithm):
    SEGMENTS = "SEGMENTS"
    IMAGERY = "IMAGERY"
    NDVI = "NDVI"
    TEXTURE_RED = "TEXTURE_RED"
    TEXTURE_GREEN = "TEXTURE_GREEN"
    TEXTURE_BLUE = "TEXTURE_BLUE"
    TEXTURE_NIR = "TEXTURE_NIR"
    INCLUDE_SHAPE_METRICS = "INCLUDE_SHAPE_METRICS"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("AddAttributesToSegments", string)

    def createInstance(self):
        return AddAttributesToSegments()

    def name(self):
        return "add_attributes_to_segments"

    def displayName(self):
        return self.tr("05 - Add Attributes to Segments")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Adds zonal texture, spectral, NDVI, and shape metric attributes to a segment layer."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.SEGMENTS,
                self.tr("Segment layer"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.IMAGERY,
                self.tr("Input imagery (bands 1..4 = RGBNIR)"),
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.NDVI,
                self.tr("NDVI raster"),
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.TEXTURE_RED,
                self.tr("Texture raster (Red)"),
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.TEXTURE_GREEN,
                self.tr("Texture raster (Green)"),
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.TEXTURE_BLUE,
                self.tr("Texture raster (Blue)"),
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.TEXTURE_NIR,
                self.tr("Texture raster (NIR)"),
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_SHAPE_METRICS,
                self.tr("Include shape metrics"),
                defaultValue=True,
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
        segments_layer = self.parameterAsVectorLayer(parameters, self.SEGMENTS, context)
        if segments_layer is None:
            raise QgsProcessingException("Could not read segment layer.")

        imagery_layer = self.parameterAsRasterLayer(parameters, self.IMAGERY, context)
        if imagery_layer is None:
            raise QgsProcessingException("Could not read imagery layer.")

        output_dest = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        if not output_dest:
            raise QgsProcessingException("Could not resolve output destination.")

        raster_specs = []

        texture_layers = {
            "red": self.parameterAsRasterLayer(parameters, self.TEXTURE_RED, context),
            "green": self.parameterAsRasterLayer(parameters, self.TEXTURE_GREEN, context),
            "blue": self.parameterAsRasterLayer(parameters, self.TEXTURE_BLUE, context),
            "nir": self.parameterAsRasterLayer(parameters, self.TEXTURE_NIR, context),
        }

        for band_label, raster_layer in texture_layers.items():
            if raster_layer:
                raster_specs.extend(build_texture_raster_specs(raster_layer.source(), band_label))

        ndvi_layer = self.parameterAsRasterLayer(parameters, self.NDVI, context)
        if ndvi_layer:
            raster_specs.append({"raster": ndvi_layer.source(), "band": 1, "prefix": "ndvi_"})

        raster_specs.extend(
            [
                {"raster": imagery_layer.source(), "band": 1, "prefix": "red_"},
                {"raster": imagery_layer.source(), "band": 2, "prefix": "green_"},
                {"raster": imagery_layer.source(), "band": 3, "prefix": "blue_"},
                {"raster": imagery_layer.source(), "band": 4, "prefix": "nir_"},
            ]
        )

        current_input = segments_layer

        for i, spec in enumerate(raster_specs):
            is_last_raster = i == len(raster_specs) - 1
            output = "TEMPORARY_OUTPUT"

            if is_last_raster and not self.parameterAsBool(parameters, self.INCLUDE_SHAPE_METRICS, context):
                output = output_dest

            params = {
                "INPUT": current_input,
                "INPUT_RASTER": spec["raster"],
                "RASTER_BAND": spec["band"],
                "COLUMN_PREFIX": spec["prefix"],
                "STATISTICS": [2],
                "OUTPUT": output,
            }

            step_name = f"Zonal stats: {spec['prefix']}"
            result = run_step(
                "native:zonalstatisticsfb",
                params,
                context,
                feedback,
            )
            current_input = result["OUTPUT"]

        include_shape = self.parameterAsBool(parameters, self.INCLUDE_SHAPE_METRICS, context)
        if include_shape:
            current_input = add_shape_metrics(
                current_input,
                output_dest,
                context=context,
                feedback=feedback,
            )
        elif not raster_specs:
            save_result = run_step(
                "native:savefeatures",
                {
                    "INPUT": current_input,
                    "OUTPUT": output_dest,
                },
                context,
                feedback,
            )
            current_input = save_result["OUTPUT"]

        add_layer_to_load_on_completion(context, current_input, "Attributed segments")

        return {
            self.OUTPUT: current_input,
        }
