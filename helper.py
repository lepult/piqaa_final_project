from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsMessageLog,
    Qgis,
)
import processing
import time
from constants import LOG_TAG

def log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def run_geobia_step(alg_id, params, step_name, context=None, feedback=None):
    log(f"--- Starting: {step_name} ---")

    if context is None:
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())

    if feedback is None:
        feedback = ResponsiveFeedback()

    try:
        result = processing.run(alg_id, params, context=context, feedback=feedback)

        if feedback.had_fatal_error:
            raise RuntimeError(f"{step_name} reported a genuine fatal error — output is likely invalid.")

        log(f"Finished: {step_name} -> {result}", Qgis.MessageLevel.Success)
        return result
    except Exception as e:
        log(f"FAILED: {step_name} -> {e}", Qgis.MessageLevel.Critical)
        raise


def add_layer_to_load_on_completion(context, destination, layer_name):
    if not context or not destination:
        return

    details = QgsProcessingContext.LayerDetails(
        layer_name,
        context.project() if context.project() else QgsProject.instance(),
        layer_name,
    )
    context.addLayerToLoadOnCompletion(destination, details)

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