# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
)
import processing

TEXTURE_EXTRACTION_XRAD_PARAMETER = 2
TEXTURE_EXTRACTION_YRAD_PARAMETER = 2
TEXTURE_EXTRACTION_NBBIN_PARAM = 8


def run_step(alg_id, params, context, feedback):
    return processing.run(alg_id, params, context=context, feedback=feedback)


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


class CreateMetricLayers(QgsProcessingAlgorithm):
    IMAGERY = "IMAGERY"
    TEXTURE_CHANNELS = "TEXTURE_CHANNELS"
    XRAD = "XRAD"
    YRAD = "YRAD"
    NBBIN = "NBBIN"
    COMPUTE_NDVI = "COMPUTE_NDVI"
    NDVI_OUTPUT = "NDVI_OUTPUT"
    TEXTURE_RED = "TEXTURE_RED"
    TEXTURE_GREEN = "TEXTURE_GREEN"
    TEXTURE_BLUE = "TEXTURE_BLUE"
    TEXTURE_NIR = "TEXTURE_NIR"

    CHANNEL_OPTIONS = ["Red", "Green", "Blue", "NIR"]

    def tr(self, string):
        return QCoreApplication.translate("CreateMetricLayers", string)

    def createInstance(self):
        return CreateMetricLayers()

    def name(self):
        return "create_metric_layers"

    def displayName(self):
        return self.tr("04 - Create Metric Layers")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Creates Haralick texture layers for selected channels and optionally "
            "creates an NDVI raster from the same imagery."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.IMAGERY,
                self.tr("Input imagery"),
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.TEXTURE_CHANNELS,
                self.tr("Texture channels"),
                options=self.CHANNEL_OPTIONS,
                allowMultiple=True,
                defaultValue=[0, 1, 2, 3],
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
            QgsProcessingParameterBoolean(
                self.COMPUTE_NDVI,
                self.tr("Compute NDVI"),
                defaultValue=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.TEXTURE_RED,
                self.tr("Texture raster (Red)"),
                optional=True,
                createByDefault=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.TEXTURE_GREEN,
                self.tr("Texture raster (Green)"),
                optional=True,
                createByDefault=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.TEXTURE_BLUE,
                self.tr("Texture raster (Blue)"),
                optional=True,
                createByDefault=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.TEXTURE_NIR,
                self.tr("Texture raster (NIR)"),
                optional=True,
                createByDefault=False,
            )
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.NDVI_OUTPUT,
                self.tr("NDVI raster"),
                optional=True,
                createByDefault=False,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        imagery_layer = self.parameterAsRasterLayer(parameters, self.IMAGERY, context)
        if imagery_layer is None:
            raise QgsProcessingException("Could not read input imagery.")

        channels = self.parameterAsEnums(parameters, self.TEXTURE_CHANNELS, context)
        if not channels:
            channels = [0, 1, 2, 3]

        xrad = self.parameterAsInt(parameters, self.XRAD, context)
        yrad = self.parameterAsInt(parameters, self.YRAD, context)
        nbbin = self.parameterAsInt(parameters, self.NBBIN, context)
        do_ndvi = self.parameterAsBool(parameters, self.COMPUTE_NDVI, context)

        channel_output_keys = {
            0: self.TEXTURE_RED,
            1: self.TEXTURE_GREEN,
            2: self.TEXTURE_BLUE,
            3: self.TEXTURE_NIR,
        }

        result_map = {
            self.TEXTURE_RED: "",
            self.TEXTURE_GREEN: "",
            self.TEXTURE_BLUE: "",
            self.TEXTURE_NIR: "",
            self.NDVI_OUTPUT: "",
        }

        for channel_idx in channels:
            output_key = channel_output_keys[channel_idx]
            output_dest = self.parameterAsOutputLayer(parameters, output_key, context)
            if not output_dest:
                continue

            params = {
                "in": imagery_layer.source(),
                "channel": channel_idx + 1,
                "step": 1,
                "parameters.xrad": xrad,
                "parameters.yrad": yrad,
                "parameters.xoff": 1,
                "parameters.yoff": 1,
                "parameters.min": 0,
                "parameters.max": 255,
                "parameters.nbbin": nbbin,
                "texture": "simple",
                "out": output_dest,
            }

            step_name = f"Texture extraction: {self.CHANNEL_OPTIONS[channel_idx]}"
            texture_result = run_step(
                "otb:HaralickTextureExtraction",
                params,
                context,
                feedback,
            )

            result_map[output_key] = texture_result["out"]

        if do_ndvi:
            ndvi_dest = self.parameterAsOutputLayer(parameters, self.NDVI_OUTPUT, context)
            if ndvi_dest:
                ndvi_result = compute_ndvi(
                    input_raster=imagery_layer.source(),
                    output_path=ndvi_dest,
                    context=context,
                    feedback=feedback,
                )
                result_map[self.NDVI_OUTPUT] = ndvi_result["OUTPUT"]

        return result_map
