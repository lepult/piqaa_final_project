# -*- coding: utf-8 -*-

"""
02 - Build Reference Layer

Inputs:
    1. AOI polygon
    2. Target polygons from 01 - Download AOI Data

Processing:
    1. Read AOI and target polygons
    2. Transform both to EPSG:25832
    3. Dissolve target polygons
    4. Clip target polygons to AOI
    5. Calculate AOI minus target = background
    6. Write target and background classes

Output:
    Reference layer containing:
        class = target
        class = background

All geometry calculations are explicitly performed in EPSG:25832.
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsFeatureSink,
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsWkbTypes,
)

import processing


def add_layer_to_load_on_completion(context, destination, layer_name):
    if not context or not destination:
        return

    details = QgsProcessingContext.LayerDetails(
        layer_name,
        context.project() if context.project() else QgsProject.instance(),
        layer_name,
    )
    context.addLayerToLoadOnCompletion(destination, details)


class BuildReferenceLayer(QgsProcessingAlgorithm):

    AOI = "AOI"
    TARGET_POLYGONS = "TARGET_POLYGONS"
    REFERENCE_LAYER = "REFERENCE_LAYER"

    TARGET_CRS = "EPSG:25832"

    def tr(self, string):
        return QCoreApplication.translate(
            "BuildReferenceLayer",
            string
        )

    def createInstance(self):
        return BuildReferenceLayer()

    def name(self):
        return "build_reference_layer"

    def displayName(self):
        return self.tr("02 - Build Reference Layer (Deprecated)")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "DEPRECATED: Use 01 - Download AOI Data instead. "
            "Creates a reference layer from the AOI and target polygons. "
            "Target polygons are dissolved and subtracted from the AOI "
            "to create background polygons. All geometry processing is "
            "performed in EPSG:25832."
        )

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AOI,
                self.tr("AOI polygon"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.TARGET_POLYGONS,
                self.tr("Target polygons"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.REFERENCE_LAYER,
                self.tr("Reference layer"),
                QgsProcessing.TypeVectorPolygon,
                None,
                True,
            )
        )

    def processAlgorithm(
        self,
        parameters,
        context,
        feedback
    ):

        feedback.pushWarning(
            "This algorithm is deprecated. Use 01 - Download AOI Data, "
            "which now builds the reference layer directly."
        )

        feedback.pushInfo(
            "=== 1. Reading inputs ==="
        )

        # =========================================================
        # Read AOI
        # =========================================================

        aoi_source = self.parameterAsSource(
            parameters,
            self.AOI,
            context
        )

        if aoi_source is None:
            raise QgsProcessingException(
                "Could not read the AOI layer."
            )

        if aoi_source.wkbType() == QgsWkbTypes.NoGeometry:
            raise QgsProcessingException(
                "AOI must contain polygon geometry."
            )

        # =========================================================
        # Read target polygons
        # =========================================================

        target_source = self.parameterAsSource(
            parameters,
            self.TARGET_POLYGONS,
            context
        )

        if target_source is None:
            raise QgsProcessingException(
                "Could not read the target polygon layer."
            )

        if target_source.wkbType() == QgsWkbTypes.NoGeometry:
            raise QgsProcessingException(
                "Target polygons must contain polygon geometry."
            )

        # =========================================================
        # Define processing CRS
        # =========================================================

        target_crs = QgsCoordinateReferenceSystem(
            self.TARGET_CRS
        )

        aoi_crs = aoi_source.sourceCrs()
        target_source_crs = target_source.sourceCrs()

        feedback.pushInfo(
            f"AOI CRS: {aoi_crs.authid()}"
        )

        feedback.pushInfo(
            f"Target polygon CRS: "
            f"{target_source_crs.authid()}"
        )

        feedback.pushInfo(
            f"Processing CRS: "
            f"{target_crs.authid()}"
        )

        # =========================================================
        # Create coordinate transforms
        # =========================================================

        aoi_transform = None

        if aoi_crs != target_crs:

            feedback.pushInfo(
                f"Transforming AOI from "
                f"{aoi_crs.authid()} to "
                f"{target_crs.authid()}..."
            )

            aoi_transform = QgsCoordinateTransform(
                aoi_crs,
                target_crs,
                QgsProject.instance()
            )

        target_transform = None

        if target_source_crs != target_crs:

            feedback.pushInfo(
                f"Transforming target polygons from "
                f"{target_source_crs.authid()} to "
                f"{target_crs.authid()}..."
            )

            target_transform = QgsCoordinateTransform(
                target_source_crs,
                target_crs,
                QgsProject.instance()
            )

        # =========================================================
        # 2. Build AOI geometry
        # =========================================================

        feedback.pushInfo(
            "=== 2. Building AOI geometry ==="
        )

        aoi_geom = None
        aoi_count = 0

        for feature in aoi_source.getFeatures():

            if feedback.isCanceled():
                return {}

            geom = feature.geometry()

            if geom is None or geom.isEmpty():
                continue

            geom = QgsGeometry(geom)

            if aoi_transform is not None:

                try:
                    geom.transform(aoi_transform)

                except Exception as exc:

                    raise QgsProcessingException(
                        f"Could not transform AOI geometry: "
                        f"{exc}"
                    )

            if aoi_geom is None:

                aoi_geom = geom

            else:

                aoi_geom = aoi_geom.combine(
                    geom
                )

            aoi_count += 1

        if aoi_geom is None or aoi_geom.isEmpty():

            raise QgsProcessingException(
                "AOI does not contain valid polygon geometry."
            )

        feedback.pushInfo(
            f"AOI features used: {aoi_count}"
        )

        feedback.pushInfo(
            "AOI successfully transformed to "
            "EPSG:25832."
        )

        # =========================================================
        # 3. Read target polygons
        # =========================================================

        feedback.pushInfo(
            "=== 3. Reading target polygons ==="
        )

        target_geometries = []

        target_count = 0
        intersect_count = 0

        for feature in target_source.getFeatures():

            if feedback.isCanceled():
                return {}

            geom = feature.geometry()

            if geom is None or geom.isEmpty():
                continue

            geom = QgsGeometry(geom)

            # -----------------------------------------------------
            # VERY IMPORTANT:
            # Transform target geometry itself, not just the layer
            # -----------------------------------------------------

            if target_transform is not None:

                try:

                    geom.transform(
                        target_transform
                    )

                except Exception as exc:

                    raise QgsProcessingException(
                        "Could not transform target "
                        f"geometry: {exc}"
                    )

            target_count += 1

            # -----------------------------------------------------
            # Check intersection in EPSG:25832
            # -----------------------------------------------------

            if not geom.intersects(aoi_geom):
                continue

            intersect_count += 1

            # -----------------------------------------------------
            # Clip target to AOI
            # -----------------------------------------------------

            clipped = geom.intersection(
                aoi_geom
            )

            if clipped is None:
                continue

            if clipped.isEmpty():
                continue

            target_geometries.append(
                clipped
            )

        feedback.pushInfo(
            f"Target features read: "
            f"{target_count}"
        )

        feedback.pushInfo(
            f"Target features intersecting AOI: "
            f"{intersect_count}"
        )

        if not target_geometries:

            raise QgsProcessingException(
                "No target polygons intersect the AOI. "
                "Make sure TARGET_POLYGONS is the output from "
                "01 - Download AOI Data."
            )

        # =========================================================
        # 4. Dissolve target polygons
        # =========================================================

        feedback.pushInfo(
            "=== 4. Dissolving target polygons ==="
        )

        dissolved_target = target_geometries[0]

        for geom in target_geometries[1:]:

            if feedback.isCanceled():
                return {}

            dissolved_target = (
                dissolved_target.combine(geom)
            )

        if (
            dissolved_target is None
            or dissolved_target.isEmpty()
        ):

            raise QgsProcessingException(
                "Dissolved target geometry is empty."
            )

        # ---------------------------------------------------------
        # Validate target geometry
        # ---------------------------------------------------------

        if not dissolved_target.isGeosValid():

            feedback.pushInfo(
                "Target geometry is invalid. "
                "Running makeValid()."
            )

            dissolved_target = (
                dissolved_target.makeValid()
            )

        if dissolved_target.isEmpty():

            raise QgsProcessingException(
                "Target geometry became empty "
                "after makeValid()."
            )

        feedback.pushInfo(
            "Target polygons successfully dissolved."
        )

        # =========================================================
        # 5. Calculate background
        # =========================================================

        feedback.pushInfo(
            "=== 5. Creating background geometry ==="
        )

        background_geom = (
            aoi_geom.difference(
                dissolved_target
            )
        )

        if background_geom is None:

            raise QgsProcessingException(
                "Could not calculate AOI minus "
                "target polygons."
            )

        if background_geom.isEmpty():

            feedback.pushWarning(
                "Background geometry is empty. "
                "Target polygons cover the entire AOI."
            )

        else:

            feedback.pushInfo(
                "Background geometry successfully created."
            )

        target_class = "target"
        background_class = "background"

        # =========================================================
        # 7. Create output sink
        # =========================================================

        feedback.pushInfo(
            "=== 6. Writing reference layer ==="
        )

        output_fields = QgsFields()

        output_fields.append(
            QgsField(
                "class",
                QVariant.String,
                "String",
                50,
                0
            )
        )

        reference_sink, reference_dest = (
            self.parameterAsSink(
                parameters,
                self.REFERENCE_LAYER,
                context,
                output_fields,
                QgsWkbTypes.MultiPolygon,
                target_crs
            )
        )

        if reference_sink is None:

            raise QgsProcessingException(
                "Could not create reference layer output."
            )

        reference_count = 0

        # =========================================================
        # 8. Write TARGET
        # =========================================================

        if (
            dissolved_target is not None
            and not dissolved_target.isEmpty()
        ):

            target_feature = QgsFeature(
                output_fields
            )

            target_feature.setGeometry(
                dissolved_target
            )

            target_feature["class"] = (
                target_class
            )

            success = reference_sink.addFeature(
                target_feature,
                QgsFeatureSink.FastInsert
            )

            if not success:

                raise QgsProcessingException(
                    "Could not write target feature."
                )

            reference_count += 1

            feedback.pushInfo(
                "Target reference polygon written."
            )

        # =========================================================
        # 9. Write BACKGROUND
        # =========================================================

        if (
            background_geom is not None
            and not background_geom.isEmpty()
        ):

            background_feature = QgsFeature(
                output_fields
            )

            background_feature.setGeometry(
                background_geom
            )

            background_feature["class"] = (
                background_class
            )

            success = reference_sink.addFeature(
                background_feature,
                QgsFeatureSink.FastInsert
            )

            if not success:

                raise QgsProcessingException(
                    "Could not write background feature."
                )

            reference_count += 1

            feedback.pushInfo(
                "Background reference polygon written."
            )

        del reference_sink

        # =========================================================
        # 10. Diagnostics
        # =========================================================

        feedback.pushInfo(
            f"Reference polygons written: "
            f"{reference_count}"
        )

        feedback.pushInfo(
            "Output CRS: EPSG:25832"
        )

        feedback.pushInfo(
            "Expected classes: "
            f"{target_class}, {background_class}"
        )

        feedback.pushInfo(
            "=== Build Reference Layer completed ==="
        )

        add_layer_to_load_on_completion(
            context,
            reference_dest,
            "Reference layer",
        )

        return {
            self.REFERENCE_LAYER: reference_dest
        }