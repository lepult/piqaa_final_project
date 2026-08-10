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
)

from constants import CLASS_FIELD_NAME
from helper import run_geobia_step
from parameters import (
    SEGMENTATION_MINSIZE_PARAM,
    SEGMENTATION_RANGER_PARAM,
    SEGMENTATION_SPATIALR_PARAM,
)


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
        if reference_source is None:
            raise QgsProcessingException("Could not read reference layer.")

        spatialr = self.parameterAsInt(parameters, self.SPATIAL_RADIUS, context)
        ranger = self.parameterAsInt(parameters, self.RANGE_RADIUS, context)
        minsize = self.parameterAsInt(parameters, self.MIN_SIZE, context)

        output_dest = self.parameterAsOutputLayer(parameters, self.LABELED_SEGMENTS, context)
        if not output_dest:
            raise QgsProcessingException("Could not resolve output destination for labeled segments.")

        seg_params = {
            "in": imagery_layer.source(),
            "spatialr": spatialr,
            "ranger": ranger,
            "minsize": minsize,
            "tilesizex": 500,
            "tilesizey": 500,
            "mode": "vector",
            "mode.vector.imfield": None,
            "mode.vector.out": "TEMPORARY_OUTPUT",
            "mode.raster.out": "TEMPORARY_OUTPUT",
            "cleanup": True,
            "outputpixeltype": 5,
        }

        seg_result = run_geobia_step(
            "otb:LargeScaleMeanShift",
            seg_params,
            "Segmentation",
            context=context,
            feedback=feedback,
        )

        seg_output = seg_result.get("mode.vector.out") or seg_result.get("OUTPUT")
        if not seg_output:
            raise QgsProcessingException("Segmentation output is missing.")

        label_params = {
            "INPUT": seg_output,
            "PREDICATE": [0],
            "JOIN": reference_source,
            "JOIN_FIELDS": [CLASS_FIELD_NAME],
            "METHOD": 2,
            "DISCARD_NONMATCHING": False,
            "PREFIX": "",
            "OUTPUT": output_dest,
        }

        label_result = run_geobia_step(
            "native:joinattributesbylocation",
            label_params,
            "Label segments from reference polygons",
            context=context,
            feedback=feedback,
        )

        return {
            self.LABELED_SEGMENTS: label_result["OUTPUT"],
        }
