# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingUtils,
)
import processing

CLASS_FIELD_NAME = "class"
SEGMENTATION_SPATIALR_PARAM = 20
SEGMENTATION_RANGER_PARAM = 15
SEGMENTATION_MINSIZE_PARAM = 50


def run_step(alg_id, params, context, feedback):
    return processing.run(alg_id, params, context=context, feedback=feedback)


class SegmentImage(QgsProcessingAlgorithm):
    IMAGERY = "IMAGERY"
    REFERENCE_LAYER = "REFERENCE_LAYER"
    SPATIAL_RADIUS = "SPATIAL_RADIUS"
    RANGE_RADIUS = "RANGE_RADIUS"
    MIN_SIZE = "MIN_SIZE"
    LABELED_SEGMENTS = "LABELED_SEGMENTS"

    def tr(self, string):
        return QCoreApplication.translate("SegmentImage", string)

    def createInstance(self):
        return SegmentImage()

    def name(self):
        return "segment_image"

    def displayName(self):
        return self.tr("03 - Segment Image")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Segments imagery with OTB LargeScaleMeanShift and transfers the class "
            "attribute from the reference polygon layer using largest-overlap join."
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
            QgsProcessingParameterFeatureSink(
                self.LABELED_SEGMENTS,
                self.tr("Labeled segments"),
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

        output_dest = self.parameterAsOutputLayer(parameters, self.LABELED_SEGMENTS, context)
        if not output_dest:
            raise QgsProcessingException("Could not resolve output destination for labeled segments.")

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

        return {
            self.LABELED_SEGMENTS: label_result["OUTPUT"],
        }
