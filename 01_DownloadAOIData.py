# -*- coding: utf-8 -*-

"""
01 - Prepare Reference

Input:
    AOI polygon feature source.

Downloads:
    1. Target polygons from the NRW ALKIS WFS
    2. NRW DOP imagery covering the supplied AOI

IMPORTANT:
    All vector and raster outputs are explicitly written in EPSG:25832.
"""

from qgis.PyQt.QtCore import QCoreApplication, QVariant

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterRasterDestination,
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
    QgsRasterLayer,
    QgsVectorLayer,
)

import processing
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import requests


def add_layer_to_load_on_completion(context, destination, layer_name):
    if not context or not destination:
        return

    details = QgsProcessingContext.LayerDetails(
        layer_name,
        context.project() if context.project() else QgsProject.instance(),
        layer_name,
    )
    context.addLayerToLoadOnCompletion(destination, details)


class DownloadAOIData(QgsProcessingAlgorithm):

    AOI = "AOI"
    FEATURE_TYPE = "FEATURE_TYPE"
    REFERENCE_LAYER = "REFERENCE_LAYER"
    AOI_IMAGERY = "AOI_IMAGERY"

    # ---------------------------------------------------------
    # Fixed target CRS
    # ---------------------------------------------------------

    TARGET_CRS = "EPSG:25832"

    # ---------------------------------------------------------
    # NRW DOP
    # ---------------------------------------------------------

    WFS_URL = "https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht"
    TARGET_CLASS_NAME = "target"
    BACKGROUND_CLASS_NAME = "background"

    DOP_INDEX_URL = (
        "https://www.opengeodata.nrw.de/produkte/geobasis/"
        "lusat/akt/dop/dop_jp2_f10/"
    )

    DOP_PATTERN = re.compile(
        r"dop10rgbi_32_(\d+)_(\d+)_1_nw_(\d+)\.jp2",
        re.IGNORECASE,
    )

    PAGE_SIZE = 4000

    # =========================================================
    # QGIS algorithm methods
    # =========================================================

    def tr(self, string):
        return QCoreApplication.translate(
            "DownloadAOIData",
            string,
        )

    def createInstance(self):
        return DownloadAOIData()

    def name(self):
        return "download_aoi_data"

    def displayName(self):
        return self.tr("01 - Prepare Reference")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Downloads NRW ALKIS target polygons and NRW DOP imagery "
            "for a polygon AOI, then directly builds a reference layer "
            "with hardcoded classes target/background. All outputs are "
            "explicitly written in EPSG:25832."
        )

    # =========================================================
    # Parameters
    # =========================================================

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AOI,
                self.tr("AOI polygon"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.FEATURE_TYPE,
                self.tr("WFS feature type"),
                defaultValue="ave:GebaeudeBauwerk",
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

        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.AOI_IMAGERY,
                self.tr("AOI-clipped DOP imagery"),
            )
        )

    # =========================================================
    # Process
    # =========================================================

    def processAlgorithm(
        self,
        parameters,
        context,
        feedback,
    ):

        def set_stage_progress(start, end, fraction, message=None):
            frac = max(0.0, min(1.0, float(fraction)))
            value = start + (end - start) * frac
            feedback.setProgress(value)
            if message:
                feedback.setProgressText(message)

        target_crs = QgsCoordinateReferenceSystem(
            self.TARGET_CRS
        )

        if not target_crs.isValid():
            raise QgsProcessingException(
                "EPSG:25832 could not be loaded."
            )

        feedback.pushInfo(
            "=============================================="
        )

        set_stage_progress(0, 100, 0.0, "Initializing workflow")
        feedback.pushInfo("01 - Prepare Reference")
        feedback.pushInfo(
            f"Fixed target CRS: {self.TARGET_CRS}"
        )
        feedback.pushInfo(
            "=============================================="
        )

        # =====================================================
        # 1. READ AOI
        # =====================================================

        feedback.pushInfo(
            "=== 1. Reading AOI ==="
        )
        set_stage_progress(0, 10, 0.0, "Reading AOI geometry")

        aoi_source = self.parameterAsSource(
            parameters,
            self.AOI,
            context,
        )

        if aoi_source is None:
            raise QgsProcessingException(
                "Could not read the AOI layer."
            )

        if aoi_source.wkbType() == QgsWkbTypes.NoGeometry:
            raise QgsProcessingException(
                "AOI must contain polygon geometry."
            )

        aoi_features = list(
            aoi_source.getFeatures()
        )

        if not aoi_features:
            raise QgsProcessingException(
                "AOI layer contains no features."
            )

        # =====================================================
        # Build single AOI geometry
        # =====================================================

        aoi_geom = None

        total_aoi = len(aoi_features)

        for i, feature in enumerate(aoi_features, 1):

            if feedback.isCanceled():
                return {}

            set_stage_progress(
                0,
                10,
                i / total_aoi,
                f"Preparing AOI geometry ({i}/{total_aoi})",
            )

            geom = feature.geometry()

            if geom is None or geom.isEmpty():
                continue

            if aoi_geom is None:
                aoi_geom = QgsGeometry(geom)
            else:
                aoi_geom = aoi_geom.combine(geom)

        if aoi_geom is None or aoi_geom.isEmpty():
            raise QgsProcessingException(
                "AOI does not contain valid polygon geometry."
            )

        # =====================================================
        # Transform AOI to EPSG:25832
        # =====================================================

        aoi_crs = aoi_source.sourceCrs()

        feedback.pushInfo(
            f"Input AOI CRS: {aoi_crs.authid()}"
        )

        if aoi_crs != target_crs:

            feedback.pushInfo(
                f"Transforming AOI from "
                f"{aoi_crs.authid()} to "
                f"{self.TARGET_CRS}..."
            )

            transform = QgsCoordinateTransform(
                aoi_crs,
                target_crs,
                QgsProject.instance(),
            )

            try:
                aoi_geom.transform(transform)

            except Exception as exc:

                raise QgsProcessingException(
                    f"Could not transform AOI to "
                    f"{self.TARGET_CRS}: {exc}"
                )

        else:

            feedback.pushInfo(
                "AOI is already in EPSG:25832."
            )

        if aoi_geom.isEmpty():
            raise QgsProcessingException(
                "AOI became empty after CRS transformation."
            )

        set_stage_progress(0, 10, 1.0, "AOI ready")

        # =====================================================
        # Create explicit EPSG:25832 AOI memory layer
        # =====================================================

        aoi_memory = QgsVectorLayer(
            "MultiPolygon?crs=EPSG:25832",
            "AOI_25832",
            "memory",
        )

        if not aoi_memory.isValid():
            raise QgsProcessingException(
                "Could not create temporary AOI layer."
            )

        aoi_provider = aoi_memory.dataProvider()

        aoi_feature = QgsFeature()
        aoi_feature.setGeometry(aoi_geom)

        if not aoi_provider.addFeature(
            aoi_feature
        ):
            raise QgsProcessingException(
                "Could not add AOI geometry."
            )

        aoi_memory.updateExtents()

        # =====================================================
        # AOI bounding box
        # =====================================================

        bbox = aoi_geom.boundingBox()

        minx = bbox.xMinimum()
        miny = bbox.yMinimum()
        maxx = bbox.xMaximum()
        maxy = bbox.yMaximum()

        feedback.pushInfo(
            f"AOI EPSG:25832 bbox: "
            f"{minx:.2f}, "
            f"{miny:.2f}, "
            f"{maxx:.2f}, "
            f"{maxy:.2f}"
        )

        # =====================================================
        # 2. DOWNLOAD WFS TARGET POLYGONS
        # =====================================================

        feedback.pushInfo(
            "=== 2. Downloading target polygons ==="
        )
        set_stage_progress(10, 45, 0.0, "Downloading WFS target polygons")

        feature_type = self.parameterAsString(
            parameters,
            self.FEATURE_TYPE,
            context,
        ).strip()

        if not feature_type:
            raise QgsProcessingException(
                "WFS feature type is empty."
            )

        # =====================================================
        # WFS filter
        # =====================================================

        filter_xml = (
            "<fes:Filter "
            "xmlns:fes='http://www.opengis.net/fes/2.0' "
            "xmlns:gml='http://www.opengis.net/gml/3.2' "
            "xmlns:ave='http://repository.gdi-de.org/"
            "schemas/adv/produkt/alkis-vereinfacht/2.0'>"

            "<fes:And>"

            "<fes:BBOX>"

            "<fes:ValueReference>"
            "ave:geometrie"
            "</fes:ValueReference>"

            "<gml:Envelope "
            "srsName='EPSG:25832'>"

            f"<gml:lowerCorner>"
            f"{minx} {miny}"
            f"</gml:lowerCorner>"

            f"<gml:upperCorner>"
            f"{maxx} {maxy}"
            f"</gml:upperCorner>"

            "</gml:Envelope>"

            "</fes:BBOX>"

            "<fes:PropertyIsEqualTo>"

            "<fes:ValueReference>"
            "ave:gfkzshh"
            "</fes:ValueReference>"

            "<fes:Literal>"
            "31001_2740"
            "</fes:Literal>"

            "</fes:PropertyIsEqualTo>"

            "</fes:And>"

            "</fes:Filter>"
        )

        # =====================================================
        # Download WFS pages
        # =====================================================

        all_features = []
        start_index = 0
        page_no = 0

        while True:

            if feedback.isCanceled():
                return {}

            request_params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": feature_type,

                # IMPORTANT:
                # Explicitly request EPSG:25832.
                "srsName": self.TARGET_CRS,

                "FILTER": filter_xml,

                "startIndex": str(
                    start_index
                ),

                "count": str(
                    self.PAGE_SIZE
                ),
            }

            url = (
                f"{self.WFS_URL}?"
                f"{urlencode(request_params)}"
            )

            feedback.pushInfo(
                f"Requesting WFS page "
                f"starting at {start_index}..."
            )
            page_no += 1
            set_stage_progress(
                10,
                35,
                min(page_no / 8.0, 1.0),
                f"Requesting WFS pages (page {page_no})",
            )

            try:

                response = requests.get(
                    url,
                    timeout=180,
                )

                response.raise_for_status()

            except Exception as exc:

                raise QgsProcessingException(
                    f"WFS request failed: {exc}"
                )

            # =================================================
            # Save GML temporarily
            # =================================================

            with tempfile.NamedTemporaryFile(
                suffix=".gml",
                delete=False,
            ) as tmp:

                tmp.write(
                    response.content
                )

                gml_path = tmp.name

            try:

                layer = QgsVectorLayer(
                    gml_path,
                    "wfs_result",
                    "ogr",
                )

                if not layer.isValid():

                    raise QgsProcessingException(
                        "QGIS could not load the "
                        "WFS GML response."
                    )

                response_crs = (
                    layer.sourceCrs()
                )

                feedback.pushInfo(
                    "WFS response CRS: "
                    f"{response_crs.authid()}"
                )

                features = list(
                    layer.getFeatures()
                )

                # =================================================
                # GUARANTEE WFS GEOMETRIES ARE EPSG:25832
                # =================================================

                if response_crs != target_crs:

                    feedback.pushInfo(
                        f"Transforming WFS geometries "
                        f"from {response_crs.authid()} "
                        f"to {self.TARGET_CRS}..."
                    )

                    transform = QgsCoordinateTransform(
                        response_crs,
                        target_crs,
                        QgsProject.instance(),
                    )

                    for feature in features:

                        geom = (
                            feature.geometry()
                        )

                        if (
                            geom is not None
                            and not geom.isEmpty()
                        ):

                            geom.transform(
                                transform
                            )

                            feature.setGeometry(
                                geom
                            )

            except QgsProcessingException:
                raise

            except Exception as exc:

                raise QgsProcessingException(
                    f"Could not parse WFS response: "
                    f"{exc}"
                )

            finally:

                try:
                    os.remove(gml_path)
                except OSError:
                    pass

            if not features:
                break

            all_features.extend(
                features
            )

            feedback.pushInfo(
                f"Received {len(features)} features "
                f"(total: {len(all_features)})."
            )

            if len(features) < self.PAGE_SIZE:
                break

            start_index += self.PAGE_SIZE

        set_stage_progress(10, 35, 1.0, "WFS download complete")

        # =====================================================
        # Exact AOI intersection
        # =====================================================

        feedback.pushInfo(
            f"Filtering {len(all_features)} "
            "WFS features to exact AOI..."
        )

        selected = []
        total_features = len(all_features)

        for i, feature in enumerate(all_features, 1):

            if feedback.isCanceled():
                return {}

            if total_features > 0 and (i == total_features or i % 200 == 0):
                set_stage_progress(
                    35,
                    45,
                    i / total_features,
                    f"Filtering AOI intersections ({i}/{total_features})",
                )

            geom = feature.geometry()

            if (
                geom is None
                or geom.isEmpty()
            ):
                continue

            if not geom.intersects(
                aoi_geom
            ):
                continue

            clipped = geom.intersection(
                aoi_geom
            )

            if (
                clipped is None
                or clipped.isEmpty()
            ):
                continue

            feature.setGeometry(
                clipped
            )

            selected.append(
                feature
            )

        feedback.pushInfo(
            "Target polygons after AOI "
            f"intersection: {len(selected)}"
        )
        set_stage_progress(35, 45, 1.0, "Target polygons filtered")

        if not selected:
            raise QgsProcessingException(
                "No target polygons intersect the AOI."
            )

        # =====================================================
        # 3. BUILD REFERENCE LAYER
        # =====================================================

        feedback.pushInfo("=== 3. Building reference layer ===")
        set_stage_progress(45, 60, 0.0, "Building reference geometries")

        target_geometries = []
        total_selected = len(selected)
        for i, feature in enumerate(selected, 1):
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            target_geometries.append(QgsGeometry(geom))
            if i == total_selected or i % 200 == 0:
                set_stage_progress(
                    45,
                    50,
                    i / total_selected,
                    f"Collecting target geometries ({i}/{total_selected})",
                )

        if not target_geometries:
            raise QgsProcessingException(
                "No valid target geometries available to build reference layer."
            )

        dissolved_target = target_geometries[0]
        total_dissolve = len(target_geometries) - 1
        for i, geom in enumerate(target_geometries[1:], 1):
            if feedback.isCanceled():
                return {}
            dissolved_target = dissolved_target.combine(geom)
            if total_dissolve > 0 and (i == total_dissolve or i % 200 == 0):
                set_stage_progress(
                    50,
                    55,
                    i / total_dissolve,
                    f"Dissolving targets ({i}/{total_dissolve})",
                )

        if dissolved_target is None or dissolved_target.isEmpty():
            raise QgsProcessingException("Dissolved target geometry is empty.")

        if not dissolved_target.isGeosValid():
            feedback.pushInfo("Target geometry is invalid. Running makeValid().")
            dissolved_target = dissolved_target.makeValid()

        if dissolved_target.isEmpty():
            raise QgsProcessingException(
                "Target geometry became empty after makeValid()."
            )

        background_geom = aoi_geom.difference(dissolved_target)
        if background_geom is None:
            raise QgsProcessingException(
                "Could not calculate AOI minus target polygons."
            )

        set_stage_progress(45, 58, 1.0, "Creating reference output")

        ref_fields = QgsFields()
        ref_fields.append(
            QgsField(
                "class",
                QVariant.String,
                "String",
                50,
                0,
            )
        )

        reference_sink, reference_dest = self.parameterAsSink(
            parameters,
            self.REFERENCE_LAYER,
            context,
            ref_fields,
            QgsWkbTypes.MultiPolygon,
            target_crs,
        )

        if reference_sink is None:
            raise QgsProcessingException("Could not create reference layer output.")

        target_feature = QgsFeature(ref_fields)
        target_feature.setGeometry(dissolved_target)
        target_feature["class"] = self.TARGET_CLASS_NAME
        if not reference_sink.addFeature(target_feature, QgsFeatureSink.FastInsert):
            raise QgsProcessingException("Could not write target reference feature.")

        if background_geom.isEmpty():
            feedback.pushWarning(
                "Background geometry is empty. Target polygons cover the entire AOI."
            )
        else:
            background_feature = QgsFeature(ref_fields)
            background_feature.setGeometry(background_geom)
            background_feature["class"] = self.BACKGROUND_CLASS_NAME
            if not reference_sink.addFeature(background_feature, QgsFeatureSink.FastInsert):
                raise QgsProcessingException("Could not write background reference feature.")

        del reference_sink

        feedback.pushInfo("Reference layer created.")
        set_stage_progress(45, 60, 1.0, "Reference layer completed")

        # =====================================================
        # 4. FIND NRW DOP TILES
        # =====================================================

        feedback.pushInfo(
            "=== 4. Finding NRW DOP tiles ==="
        )
        set_stage_progress(60, 78, 0.0, "Loading DOP tile index")

        try:

            response = requests.get(
                self.DOP_INDEX_URL,
                timeout=180,
                stream=True,
            )

            response.raise_for_status()
            set_stage_progress(60, 65, 1.0, "DOP tile index downloaded")

        except Exception as exc:

            raise QgsProcessingException(
                f"Could not download DOP tile index: "
                f"{exc}"
            )

        response.raw.decode_content = True

        filenames = []

        try:

            for _event, elem in ET.iterparse(
                response.raw,
                events=("end",),
            ):

                if elem.tag != "file":
                    continue

                name = elem.get(
                    "name",
                    "",
                )

                if name.lower().endswith(
                    ".jp2"
                ):

                    filenames.append(
                        name
                    )

                elem.clear()

            set_stage_progress(65, 70, 1.0, "DOP tile index parsed")

        except Exception as exc:

            raise QgsProcessingException(
                f"Could not parse DOP tile index: "
                f"{exc}"
            )

        feedback.pushInfo(
            f"Found {len(filenames)} "
            "DOP files in index."
        )

        # =====================================================
        # Find newest tile for each position
        # =====================================================

        by_tile = {}
        total_filenames = len(filenames)

        for i, fname in enumerate(filenames, 1):

            match = (
                self.DOP_PATTERN.search(
                    fname
                )
            )

            if not match:
                continue

            easting_km, northing_km, year = (
                match.groups()
            )

            tile_e = (
                int(easting_km)
                * 1000
            )

            tile_n = (
                int(northing_km)
                * 1000
            )

            tile_e_max = (
                tile_e + 1000
            )

            tile_n_max = (
                tile_n + 1000
            )

            intersects = not (
                tile_e_max < minx
                or tile_e > maxx
                or tile_n_max < miny
                or tile_n > maxy
            )

            if not intersects:
                continue

            key = (
                easting_km,
                northing_km,
            )

            year_int = int(year)

            if (
                key not in by_tile
                or year_int
                > by_tile[key][0]
            ):

                by_tile[key] = (
                    year_int,
                    fname,
                )

            if total_filenames > 0 and (i == total_filenames or i % 1000 == 0):
                set_stage_progress(
                    70,
                    78,
                    i / total_filenames,
                    f"Selecting newest DOP tiles ({i}/{total_filenames})",
                )

        matching = [
            value[1]
            for value in by_tile.values()
        ]

        feedback.pushInfo(
            f"{len(matching)} newest DOP tile(s) "
            "intersect the AOI bbox."
        )

        if not matching:

            raise QgsProcessingException(
                "No DOP tiles were found for the AOI."
            )

        # =====================================================
        # 5. DOWNLOAD DOP TILES
        # =====================================================

        feedback.pushInfo(
            "=== 5. Downloading DOP tiles ==="
        )
        set_stage_progress(78, 90, 0.0, "Downloading DOP tiles")

        temp_dir = tempfile.mkdtemp(
            prefix="qgis_lbs_dop_"
        )

        tile_paths = []

        try:

            for i, fname in enumerate(
                sorted(matching),
                1,
            ):

                if feedback.isCanceled():
                    return {}

                url = (
                    self.DOP_INDEX_URL
                    + fname
                )

                path = os.path.join(
                    temp_dir,
                    fname,
                )

                feedback.pushInfo(
                    f"Downloading tile "
                    f"{i}/{len(matching)}: "
                    f"{fname}"
                )
                set_stage_progress(
                    78,
                    90,
                    i / len(matching),
                    f"Downloading DOP tiles ({i}/{len(matching)})",
                )

                try:

                    r = requests.get(
                        url,
                        timeout=180,
                    )

                    r.raise_for_status()

                except Exception as exc:

                    raise QgsProcessingException(
                        f"Failed to download "
                        f"{fname}: {exc}"
                    )

                with open(
                    path,
                    "wb",
                ) as f:

                    f.write(
                        r.content
                    )

                tile_paths.append(
                    path
                )

            # =================================================
            # Build VRT
            # =================================================

            feedback.pushInfo(
                "Building DOP mosaic..."
            )
            set_stage_progress(90, 94, 0.0, "Building DOP mosaic")

            vrt_path = os.path.join(
                temp_dir,
                "dop_mosaic.vrt",
            )

            processing.run(
                "gdal:buildvirtualraster",
                {
                    "INPUT": tile_paths,
                    "RESOLUTION": 0,
                    "SEPARATE": False,
                    "PROJ_DIFFERENCE": False,
                    "ADD_ALPHA": False,

                    # Explicit CRS
                    "ASSIGN_CRS": target_crs,

                    "RESAMPLING": 0,
                    "OUTPUT": vrt_path,
                },
                context=context,
                feedback=feedback,
            )
            set_stage_progress(90, 94, 1.0, "DOP mosaic ready")

            # =================================================
            # 6. CLIP DOP TO AOI
            # =================================================

            feedback.pushInfo(
                "=== 6. Clipping DOP imagery to AOI ==="
            )
            set_stage_progress(94, 97, 0.0, "Clipping DOP to AOI")

            imagery_dest = (
                self.parameterAsOutputLayer(
                    parameters,
                    self.AOI_IMAGERY,
                    context,
                )
            )

            if not imagery_dest:

                raise QgsProcessingException(
                    "Could not determine imagery "
                    "output path."
                )

            processing.run(
                "gdal:cliprasterbymasklayer",
                {
                    "INPUT": vrt_path,

                    # AOI is explicitly EPSG:25832
                    "MASK": aoi_memory,

                    # Explicit raster CRS
                    "SOURCE_CRS": target_crs,
                    "TARGET_CRS": target_crs,

                    "NODATA": 0,
                    "ALPHA_BAND": False,
                    "CROP_TO_CUTLINE": True,
                    "KEEP_RESOLUTION": True,
                    "SET_RESOLUTION": False,
                    "X_RESOLUTION": None,
                    "Y_RESOLUTION": None,
                    "MULTITHREADING": False,
                    "OPTIONS": "",
                    "DATA_TYPE": 0,
                    "EXTRA": "",

                    "OUTPUT": imagery_dest,
                },
                context=context,
                feedback=feedback,
            )
            set_stage_progress(94, 97, 1.0, "AOI imagery clipped")

        finally:

            try:

                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True,
                )

            except Exception:
                pass

        # =====================================================
        # 7. VERIFY OUTPUT CRS
        # =====================================================

        feedback.pushInfo(
            "=== 7. Verifying output CRS ==="
        )
        set_stage_progress(97, 100, 0.0, "Verifying outputs")

        # -----------------------------------------------------
        # Verify vector output
        # -----------------------------------------------------

        reference_output_layer = QgsVectorLayer(
            reference_dest,
            "reference_output_check",
            "ogr",
        )

        if not reference_output_layer.isValid():

            raise QgsProcessingException(
                "Could not reopen the reference layer "
                "output for CRS verification."
            )

        vector_crs = (
            reference_output_layer.sourceCrs()
        )

        feedback.pushInfo(
            "Reference layer output CRS: "
            f"{vector_crs.authid()}"
        )

        if vector_crs != target_crs:

            raise QgsProcessingException(
                "CRS verification FAILED. "
                "Reference layer is "
                f"{vector_crs.authid()} instead of "
                f"{self.TARGET_CRS}."
            )

        # -----------------------------------------------------
        # Verify raster output
        # -----------------------------------------------------

        imagery_layer = QgsRasterLayer(
            imagery_dest,
            "imagery_output_check",
        )

        if imagery_layer.isValid():

            raster_crs = (
                imagery_layer.crs()
            )

            feedback.pushInfo(
                "DOP imagery output CRS: "
                f"{raster_crs.authid()}"
            )

            if raster_crs != target_crs:

                raise QgsProcessingException(
                    "CRS verification FAILED. "
                    "DOP imagery is "
                    f"{raster_crs.authid()} instead of "
                    f"{self.TARGET_CRS}."
                )

        set_stage_progress(97, 100, 1.0, "Workflow complete")

        # =====================================================
        # COMPLETE
        # =====================================================

        feedback.pushInfo(
            "=============================================="
        )

        feedback.pushInfo(
            "Prepare Reference completed successfully."
        )

        feedback.pushInfo(
            f"Reference layer CRS: {self.TARGET_CRS}"
        )

        feedback.pushInfo(
            f"DOP imagery CRS: {self.TARGET_CRS}"
        )

        feedback.pushInfo(
            "=============================================="
        )

        add_layer_to_load_on_completion(
            context,
            imagery_dest,
            "AOI imagery",
        )

        add_layer_to_load_on_completion(
            context,
            reference_dest,
            "Reference layer",
        )

        return {
            self.REFERENCE_LAYER: reference_dest,
            self.AOI_IMAGERY: imagery_dest,
        }