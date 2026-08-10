"""
GEOBIA Workflow Script
======================
Run this from the QGIS Python console.

Pipeline so far:
    1. Segmentation (OTB LargeScaleMeanShift)
    2. Segment labeling by overlap with reference class polygons

Each step is run through run_geobia_step(), which:
    - Logs progress/commands/errors to both the console and the
      QGIS "Log Messages" panel (category: GEOBIA)
    - Keeps the QGIS GUI responsive during long-running steps
    - Filters out known-benign OGR/GeoPackage transaction errors
      that OTB sometimes reports as FATAL even when the output
      data is written correctly
    - Raises an exception (stopping the pipeline) on genuine
      fatal errors, so a broken step can't silently feed bad
      data into the next one
"""

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsMessageLog,
    QgsVectorLayer,
    Qgis,
)
from qgis.utils import iface
import processing
import time







class ResponsiveFeedback(QgsProcessingFeedback):
    # Known benign OGR/GeoPackage transaction quirks - data is often
    # still written correctly despite these being reported as FATAL.
    BENIGN_ERROR_PATTERNS = [
        "Unable to commit transaction",
        "Transaction not established",
    ]

    def __init__(self):
        super().__init__()
        self.had_fatal_error = False

    def setProgress(self, progress):
        log(f"Progress: {progress:.1f}%")
        QCoreApplication.processEvents()  # keeps GUI responsive without real threading
        super().setProgress(progress)

    def pushCommandInfo(self, info):
        log(f"COMMAND: {info}")
        super().pushCommandInfo(info)

    def reportError(self, error, fatalError=False):
        level = Qgis.MessageLevel.Critical if fatalError else Qgis.MessageLevel.Warning
        log(f"{'FATAL' if fatalError else 'warning'}: {error}", level)

        is_benign = any(pattern in str(error) for pattern in self.BENIGN_ERROR_PATTERNS)
        if fatalError and not is_benign:
            self.had_fatal_error = True
        elif fatalError and is_benign:
            log("(treated as benign, pipeline will continue)", Qgis.MessageLevel.Warning)

        super().reportError(error, fatalError)


def run_geobia_step(alg_id, params, step_name):
    log(f"--- Starting: {step_name} ---")
    QApplication.setOverrideCursor(Qt.WaitCursor)  # visual "busy" indicator
    try:
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = ResponsiveFeedback()
        result = processing.run(alg_id, params, context=context, feedback=feedback)

        if feedback.had_fatal_error:
            raise RuntimeError(f"{step_name} reported a genuine fatal error — output is likely invalid.")

        log(f"Finished: {step_name} -> {result}", Qgis.MessageLevel.Success)
        return result
    except Exception as e:
        log(f"FAILED: {step_name} -> {e}", Qgis.MessageLevel.Critical)
        iface.messageBar().pushCritical("GEOBIA", f"{step_name} failed: {e}")
        raise
    finally:
        QApplication.restoreOverrideCursor()

# ============================================================
# Step 1: Segmentation (OTB LargeScaleMeanShift)
# ============================================================
seg_params = {
    'in': f'{PROJECT_PATH}/{AOI_IMAGERY_NAME}',
    'spatialr': SEGMENTATION_SPATIALR_PARAM,
    'ranger': SEGMENTATION_RANGER_PARAM,
    'minsize': SEGMENTATION_MINSIZE_PARAM,
    'tilesizex': 500,
    'tilesizey': 500,
    'mode': 'vector',
    'mode.vector.imfield': None,
    'mode.vector.out': f'{PROJECT_PATH}/{SEGMENTED_FILE_NAME}',
    'mode.raster.out': 'TEMPORARY_OUTPUT',
    'cleanup': True,
    'outputpixeltype': 5,
}

seg_result = run_geobia_step('otb:LargeScaleMeanShift', seg_params, "Segmentation")
iface.messageBar().pushSuccess("GEOBIA", "Segmentation complete.")


# ============================================================
# Step 2: Label segments by overlap with reference class polygons
# ============================================================
label_params = {
    'INPUT': f'{PROJECT_PATH}/{SEGMENTED_FILE_NAME}|layername={SEGMENTED_LAYER_NAME}',
    'PREDICATE': [0],  # intersects
    'JOIN': f'{CLASS_POLYGON_FILE}|layername={CLASS_POLYGON_LAYER}',
    'JOIN_FIELDS': [],  # empty = join all fields from the class polygon layer
    'METHOD': 2,        # take attributes of feature with largest overlap
    'DISCARD_NONMATCHING': False,
    'PREFIX': '',
    'OUTPUT': (
        f"ogr:dbname='{PROJECT_PATH}/{LABELED_FILE_NAME}' "
        f'table="{LABELED_TABLE_NAME}" (geom)'
    ),
}

label_result = run_geobia_step(
    'native:joinattributesbylocation', label_params, "Label segments by class polygon"
)
iface.messageBar().pushSuccess("GEOBIA", "Segment labeling complete.")


# ============================================================
# Validation: check the labeled output before trusting it
# ============================================================
labeled_path = f'{PROJECT_PATH}/{LABELED_FILE_NAME}'
labeled = QgsVectorLayer(labeled_path, 'labeled_check', 'ogr')

log(f"Validating labeled output: {labeled_path}")
log(f"  Valid layer: {labeled.isValid()}")

if labeled.isValid():
    feature_count = labeled.featureCount()
    log(f"  Feature count: {feature_count}")

    fields = [f.name() for f in labeled.fields()]
    log(f"  Fields: {fields}")

    if CLASS_FIELD_NAME in fields:
        null_count = sum(1 for f in labeled.getFeatures() if f[CLASS_FIELD_NAME] is None)
        log(f"  Segments with no matching class ('{CLASS_FIELD_NAME}' is NULL): {null_count} / {feature_count}")
    else:
        log(
            f"  WARNING: expected class field '{CLASS_FIELD_NAME}' not found in joined fields. "
            f"Update CLASS_FIELD_NAME to match one of: {fields}",
            Qgis.MessageLevel.Warning,
        )
else:
    log("  WARNING: labeled output layer failed to load — check the log above for errors.", Qgis.MessageLevel.Critical)
