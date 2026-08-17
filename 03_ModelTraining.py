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
        return self.tr("03 - Random Forest Classification Training")

    def group(self):
        return self.tr("GEOBIA Classifier")

    def groupId(self):
        return "geobia_classifier"

    def shortHelpString(self):
        return self.tr(
            "Creates numeric class_id from class (target/background), splits into "
            "train/validation sets, trains OTB Random Forest, classifies validation set, "
            "and writes metrics (accuracy, precision, recall, F1, TP, FP, TN, FN)."
        )

    def initAlgorithm(self, config=None):
        segments_param = QgsProcessingParameterFeatureSource(
            self.FEATURE_SEGMENTS,
            self.tr("Input attributed segments"),
            [QgsProcessing.TypeVectorPolygon],
        )
        segments_param.setHelp(
            self.tr(
                "Polygon segments with class field ('target'/'background') and numeric feature fields. "
                "Typically output from Step 02 - Segmentation."
            )
        )
        self.addParameter(segments_param)

        fields_param = QgsProcessingParameterField(
            self.FEATURE_FIELDS,
            self.tr("Feature fields for RF"),
            parentLayerParameterName=self.FEATURE_SEGMENTS,
            type=QgsProcessingParameterField.Numeric,
            allowMultiple=True,
        )
        fields_param.setHelp(
            self.tr(
                "Select one or more numeric fields to use as features for Random Forest training. "
                "Examples: textures (red_energy, red_entropy), NDVI, band means, shape metrics."
            )
        )
        self.addParameter(fields_param)

        val_percent_param = QgsProcessingParameterNumber(
            self.VALIDATION_PERCENT,
            self.tr("Validation percent"),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=30.0,
            minValue=1.0,
            maxValue=99.0,
        )
        val_percent_param.setHelp(
            self.tr(
                "Percentage of segments used for validation (remainder for training). "
                "Default: 30% validation, 70% training."
            )
        )
        self.addParameter(val_percent_param)

        max_depth_param = QgsProcessingParameterNumber(
            self.RF_MAX_DEPTH,
            self.tr("RF max tree depth"),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=5,
            minValue=1,
        )
        max_depth_param.setHelp(
            self.tr(
                "Maximum depth of Random Forest trees. Deeper = more complex model, higher overfit risk. "
                "Default: 5."
            )
        )
        self.addParameter(max_depth_param)

        min_samples_param = QgsProcessingParameterNumber(
            self.RF_MIN_SAMPLES,
            self.tr("RF min samples per node"),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=10,
            minValue=1,
        )
        min_samples_param.setHelp(
            self.tr(
                "Minimum number of samples required to split a node. "
                "Higher = smoother model, lower risk of overfitting. Default: 10."
            )
        )
        self.addParameter(min_samples_param)

        nbtrees_param = QgsProcessingParameterNumber(
            self.RF_NB_TREES,
            self.tr("RF number of trees"),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=100,
            minValue=1,
        )
        nbtrees_param.setHelp(
            self.tr(
                "Number of decision trees in the ensemble. More trees = better generalization but slower. "
                "Default: 100."
            )
        )
        self.addParameter(nbtrees_param)

        model_param = QgsProcessingParameterFileDestination(
            self.MODEL_FILE,
            self.tr("Model output file"),
            fileFilter="Model files (*.model *.file *.txt);;All files (*.*)",
        )
        model_param.setHelp(
            self.tr(
                "Path to save the trained Random Forest model. Use for predicting on new data."
            )
        )
        self.addParameter(model_param)

        metrics_param = QgsProcessingParameterFileDestination(
            self.METRICS_FILE,
            self.tr("Metrics output text file"),
            fileFilter="Text files (*.txt);;All files (*.*)",
        )
        metrics_param.setHelp(
            self.tr(
                "Path to save validation metrics (accuracy, precision, recall, F1, confusion matrix counts)."
            )
        )
        self.addParameter(metrics_param)

    def processAlgorithm(self, parameters, context, feedback):
        def set_stage_progress(start, end, fraction, message=None):
            frac = max(0.0, min(1.0, float(fraction)))
            value = start + (end - start) * frac
            feedback.setProgress(value)
            if message:
                feedback.setProgressText(message)

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

        set_stage_progress(0, 20, 0.1, "Validating input layer...")
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

        set_stage_progress(20, 35, 0.2, "Creating class_id field...")
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

        set_stage_progress(35, 45, 0.3, "Cleaning data and creating split field...")
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

        set_stage_progress(45, 60, 0.4, "Splitting into training and validation sets...")
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

        set_stage_progress(60, 70, 0.5, "Validating training and validation sets...")
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

        set_stage_progress(70, 75, 0.6, "Validating feature fields...")
        feedback.pushInfo(f"Training features: {train_count}")
        feedback.pushInfo(f"Validation features: {valid_count}")

        set_stage_progress(75, 80, 0.7, "Training Random Forest model...")
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

        set_stage_progress(80, 90, 0.8, "Predicting on validation set...")
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

        set_stage_progress(90, 95, 0.9, "Computing metrics...")
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

        set_stage_progress(95, 100, 0.95, "Finalizing output...")
        with open(metrics_file, "w", encoding="utf-8") as f:
            f.write("\n".join(metrics_lines) + "\n")

        set_stage_progress(95, 100, 1.0, "Complete")
        return {
            self.MODEL_FILE: model_file,
            self.METRICS_FILE: metrics_file,
        }
