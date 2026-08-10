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
from constants import LOG_TAG

def log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(msg, LOG_TAG, level)
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

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