# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFileDestination,
    QgsProcessingUtils,
    QgsVectorLayer,
)
import processing


def run_step(alg_id, params, context, feedback):
    return processing.run(alg_id, params, context=context, feedback=feedback)


class RandomForestClassification(QgsProcessingAlgorithm):
    FEATURE_SEGMENTS = "FEATURE_SEGMENTS"
    FEATURE_FIELDS = "FEATURE_FIELDS"
    VALIDATION_PERCENT = "VALIDATION_PERCENT"
    RF_MAX_DEPTH = "RF_MAX_DEPTH"
    RF_MIN_SAMPLES = "RF_MIN_SAMPLES"
    RF_NB_TREES = "RF_NB_TREES"
    MODEL_FILE = "MODEL_FILE"
    METRICS_FILE = "METRICS_FILE"

    def tr(self, string):
        return QCoreApplication.translate("RandomForestClassification", string)

    def createInstance(self):
        return RandomForestClassification()

    def name(self):
        return "random_forest_classification"

    def displayName(self):
        return self.tr("06 - Random Forest Classification")

    def group(self):
        return self.tr("LBS Workflow")

    def groupId(self):
        return "lbs_workflow"

    def shortHelpString(self):
        return self.tr(
            "Creates numeric class_id from class (target/background), splits into "
            "train/validation sets, trains OTB Random Forest, classifies validation set, "
            "and writes metrics (accuracy, precision, recall, F1, TP, FP, TN, FN)."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.FEATURE_SEGMENTS,
                self.tr("Input attributed segments"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.FEATURE_FIELDS,
                self.tr("Feature fields for RF"),
                parentLayerParameterName=self.FEATURE_SEGMENTS,
                type=QgsProcessingParameterField.Numeric,
                allowMultiple=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.VALIDATION_PERCENT,
                self.tr("Validation percent"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=30.0,
                minValue=1.0,
                maxValue=99.0,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.RF_MAX_DEPTH,
                self.tr("RF max tree depth"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=5,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.RF_MIN_SAMPLES,
                self.tr("RF min samples per node"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=10,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.RF_NB_TREES,
                self.tr("RF number of trees"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=100,
                minValue=1,
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.MODEL_FILE,
                self.tr("Model output file"),
                fileFilter="Model files (*.model *.file *.txt);;All files (*.*)",
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.METRICS_FILE,
                self.tr("Metrics output text file"),
                fileFilter="Text files (*.txt);;All files (*.*)",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        segments_layer = self.parameterAsVectorLayer(parameters, self.FEATURE_SEGMENTS, context)
        if segments_layer is None:
            raise QgsProcessingException("Could not read input attributed segments layer.")

        feature_fields = self.parameterAsFields(parameters, self.FEATURE_FIELDS, context)
        if not feature_fields:
            raise QgsProcessingException("Select at least one numeric feature field for RF.")

        validation_percent = self.parameterAsDouble(parameters, self.VALIDATION_PERCENT, context)
        rf_max_depth = self.parameterAsInt(parameters, self.RF_MAX_DEPTH, context)
        rf_min_samples = self.parameterAsInt(parameters, self.RF_MIN_SAMPLES, context)
        rf_nb_trees = self.parameterAsInt(parameters, self.RF_NB_TREES, context)

        model_file = self.parameterAsFileOutput(parameters, self.MODEL_FILE, context)
        metrics_file = self.parameterAsFileOutput(parameters, self.METRICS_FILE, context)

        input_fields = [f.name() for f in segments_layer.fields()]
        if "class" not in input_fields:
            raise QgsProcessingException('Input layer must contain text field "class".')

        current = segments_layer

        if "class_id" in input_fields:
            delete_res = run_step(
                "native:deletecolumn",
                {
                    "INPUT": current,
                    "COLUMN": ["class_id"],
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
                context,
                feedback,
            )
            current = delete_res["OUTPUT"]

        class_id_expr = (
            "CASE "
            "WHEN \"class\" = 'target' THEN 1 "
            "WHEN \"class\" = 'background' THEN 0 "
            "ELSE NULL END"
        )

        class_id_res = run_step(
            "native:fieldcalculator",
            {
                "INPUT": current,
                "FIELD_NAME": "class_id",
                "FIELD_TYPE": 1,
                "FIELD_LENGTH": 10,
                "FIELD_PRECISION": 0,
                "FORMULA": class_id_expr,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            context,
            feedback,
        )
        current = class_id_res["OUTPUT"]

        clean_res = run_step(
            "native:extractbyexpression",
            {
                "INPUT": current,
                "EXPRESSION": "\"class_id\" IS NOT NULL",
                "OUTPUT": "TEMPORARY_OUTPUT",
                "FAIL_OUTPUT": "TEMPORARY_OUTPUT",
            },
            context,
            feedback,
        )
        current = clean_res["OUTPUT"]

        split_res = run_step(
            "native:fieldcalculator",
            {
                "INPUT": current,
                "FIELD_NAME": "__rf_rand",
                "FIELD_TYPE": 0,
                "FIELD_LENGTH": 20,
                "FIELD_PRECISION": 10,
                "FORMULA": "randf(0,1)",
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            context,
            feedback,
        )
        current = split_res["OUTPUT"]

        frac = validation_percent / 100.0
        expr_val = "\"__rf_rand\" <= {:.10f}".format(frac)
        expr_train = "\"__rf_rand\" > {:.10f}".format(frac)

        validation_res = run_step(
            "native:extractbyexpression",
            {
                "INPUT": current,
                "EXPRESSION": expr_val,
                "OUTPUT": QgsProcessingUtils.generateTempFilename("rf_validation.gpkg"),
                "FAIL_OUTPUT": "TEMPORARY_OUTPUT",
            },
            context,
            feedback,
        )
        validation_path = validation_res["OUTPUT"]

        train_res = run_step(
            "native:extractbyexpression",
            {
                "INPUT": current,
                "EXPRESSION": expr_train,
                "OUTPUT": QgsProcessingUtils.generateTempFilename("rf_training.gpkg"),
                "FAIL_OUTPUT": "TEMPORARY_OUTPUT",
            },
            context,
            feedback,
        )
        training_path = train_res["OUTPUT"]

        train_layer = QgsVectorLayer(training_path, "rf_training_check", "ogr")
        valid_layer = QgsVectorLayer(validation_path, "rf_validation_check", "ogr")
        if not train_layer.isValid() or not valid_layer.isValid():
            raise QgsProcessingException("Could not open training or validation split.")

        train_count = train_layer.featureCount()
        valid_count = valid_layer.featureCount()
        if train_count == 0 or valid_count == 0:
            raise QgsProcessingException(
                "Train/validation split produced empty layer. Adjust validation percent."
            )

        train_fields = {f.name() for f in train_layer.fields()}
        valid_fields = {f.name() for f in valid_layer.fields()}
        missing_train = [name for name in feature_fields if name not in train_fields]
        missing_valid = [name for name in feature_fields if name not in valid_fields]
        if missing_train:
            raise QgsProcessingException(
                "Training split is missing selected RF feature field(s): "
                + ", ".join(missing_train)
            )
        if missing_valid:
            raise QgsProcessingException(
                "Validation split is missing selected RF feature field(s): "
                + ", ".join(missing_valid)
            )

        feedback.pushInfo(f"Training features: {train_count}")
        feedback.pushInfo(f"Validation features: {valid_count}")

        train_params = {
            "io.vd": [training_path],
            "io.stats": "",
            "io.out": model_file,
            "io.confmatout": "TEMPORARY_OUTPUT",
            "layer": 0,
            "feat": feature_fields,
            "valid.vd": [validation_path],
            "valid.layer": 0,
            "cfield": "class_id",
            "v": True,
            "classifier": "rf",
            "classifier.rf.max": rf_max_depth,
            "classifier.rf.min": rf_min_samples,
            "classifier.rf.ra": 0,
            "classifier.rf.cat": 10,
            "classifier.rf.var": 0,
            "classifier.rf.nbtrees": rf_nb_trees,
            "classifier.rf.acc": 0.01,
            "rand": 0,
        }

        run_step("otb:TrainVectorClassifier", train_params, context, feedback)

        pred_path = QgsProcessingUtils.generateTempFilename("rf_validation_pred.gpkg")
        classifier_attempts = [
            {
                "in": validation_path,
                "instat": "",
                "model": model_file,
                "feat": feature_fields,
                "cfield": "rf_pred",
                "out": pred_path,
            },
            {
                "in": validation_path,
                "model": model_file,
                "feat": feature_fields,
                "cfield": "rf_pred",
                "out": pred_path,
            },
        ]

        last_exc = None
        for cparams in classifier_attempts:
            try:
                run_step("otb:VectorClassifier", cparams, context, feedback)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            raise QgsProcessingException(f"Validation classification failed: {last_exc}")

        pred_layer = QgsVectorLayer(pred_path, "rf_validation_pred", "ogr")
        if not pred_layer.isValid():
            raise QgsProcessingException("Could not open predicted validation layer.")

        pred_field = "rf_pred"
        pred_fields = [f.name() for f in pred_layer.fields()]
        if pred_field not in pred_fields:
            fallback = [n for n in pred_fields if "pred" in n.lower()]
            if not fallback:
                raise QgsProcessingException(
                    f'Prediction field "{pred_field}" not found in validation prediction output.'
                )
            pred_field = fallback[0]

        tp = fp = tn = fn = 0
        used = 0

        for feat in pred_layer.getFeatures():
            true_val = feat["class_id"]
            pred_val = feat[pred_field]
            if true_val is None or pred_val is None:
                continue

            try:
                t = int(round(float(true_val)))
                p = int(round(float(pred_val)))
            except Exception:
                continue

            if t == 1 and p == 1:
                tp += 1
            elif t == 0 and p == 1:
                fp += 1
            elif t == 0 and p == 0:
                tn += 1
            elif t == 1 and p == 0:
                fn += 1
            used += 1

        if used == 0:
            raise QgsProcessingException("No comparable validation records for metrics computation.")

        accuracy = (tp + tn) / used
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        metrics_lines = [
            "Random Forest validation metrics",
            f"training_count={train_count}",
            f"validation_count={valid_count}",
            f"evaluated_count={used}",
            f"TP={tp}",
            f"FP={fp}",
            f"TN={tn}",
            f"FN={fn}",
            f"accuracy={accuracy:.6f}",
            f"precision={precision:.6f}",
            f"recall={recall:.6f}",
            f"f1={f1:.6f}",
        ]

        for line in metrics_lines:
            feedback.pushInfo(line)

        with open(metrics_file, "w", encoding="utf-8") as f:
            f.write("\n".join(metrics_lines) + "\n")

        return {
            self.MODEL_FILE: model_file,
            self.METRICS_FILE: metrics_file,
        }
