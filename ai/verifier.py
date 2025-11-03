# ai/verifier.py — ONNX → TF → heuristic pipeline (cleaned & fixed)

import os, json, piexif, imagehash
from PIL import Image
import numpy as np

# --- Optional backends ---
try:
    import onnxruntime as ort  # tiny, fast runtime
except Exception:
    ort = None

try:
    import tensorflow as tf   # optional; only used if available AND no ONNX
except Exception:
    tf = None

# --- Env + constants ---
TARGET_H, TARGET_W = 224, 224

# legacy/env knobs (kept for compatibility)
PV_THRESHOLD         = float(os.getenv("PV_THRESHOLD", "0.50"))          # only used for binary TF models
PV_VALID_CLASS_INDEX = int(os.getenv("PV_VALID_CLASS_INDEX", "0"))       # fallback if class_map missing
PV_ACTION_CUTOFF     = float(os.getenv("PV_ACTION_CUTOFF", "0.50"))
MODEL_PATH           = os.getenv("PV_MODEL_PATH", "photo_verifier.onnx")
MODEL_VERSION        = os.getenv("PV_MODEL_VERSION", "smart_v1")
CLASS_MAP_PATH_ENV   = os.getenv("PV_CLASS_MAP_PATH", "")                # optional override

# Heuristic knobs
HEURISTIC_FLOOR      = float(os.getenv("PV_HEURISTIC_FLOOR", "0.10"))
HEURISTIC_BIAS       = float(os.getenv("PV_HEURISTIC_BIAS", "0.00"))  # keep 0 while calibrating

# Duplicate logic knobs
DISABLE_DUP_PENALTY  = os.getenv("PV_DISABLE_DUP_PENALTY", "0") == "1"
DUP_DISTANCE         = int(os.getenv("PV_DUP_DISTANCE", "5"))
DUP_PENALTY_VALUE    = float(os.getenv("PV_DUP_PENALTY", "0.40"))

def _prep(path: str) -> np.ndarray:
    """Load & resize to model input. IMPORTANT: feed 0..255 float to ONNX (preprocessing is inside the exported model)."""
    img = Image.open(path).convert("RGB").resize((TARGET_W, TARGET_H))
    x = np.array(img, dtype=np.float32)[None, ...]  # (1,H,W,3), 0..255
    return x

def _softmax_np(v):
    v = v - np.max(v)
    e = np.exp(v)
    return e / (np.sum(e) + 1e-9)

def compute_phash(path):
    return str(imagehash.phash(Image.open(path).convert("RGB")))

def exif_time_okay(path):
    try:
        exif = piexif.load(path)
        dt = exif["Exif"].get(piexif.ExifIFD.DateTimeOriginal) or exif["0th"].get(piexif.ImageIFD.DateTime)
        if not dt:
            return None  # neutral if missing
        return True      # MVP: presence = OK
    except Exception:
        return None

# ------------ Heuristic -------------
def _image_entropy(arr01: np.ndarray) -> float:
    gray = (0.299*arr01[...,0] + 0.587*arr01[...,1] + 0.114*arr01[...,2]).astype(np.float32)
    hist, _ = np.histogram(gray, bins=32, range=(0.0,1.0), density=True)
    hist = hist + 1e-8
    ent = -np.sum(hist * np.log2(hist))
    ent_norm = ent / np.log2(32)
    return float(max(0.0, min(1.0, ent_norm)))

def simple_relevance_heuristic(path: str) -> float:
    img = Image.open(path).convert("RGB").resize((320, 320))
    arr = np.asarray(img, dtype=np.float32) / 255.0

    R, G, B = arr[...,0], arr[...,1], arr[...,2]
    gray = (0.299*R + 0.587*G + 0.114*B)

    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    H = min(gx.shape[0], gy.shape[0]); W = min(gx.shape[1], gy.shape[1])
    mag = np.sqrt(gx[:H,:W]**2 + gy[:H,:W]**2)
    edge_thr = np.percentile(mag, 60)
    edge_density = float((mag > edge_thr).mean())

    row_energy = float(np.mean(gx))
    col_energy = float(np.mean(gy))
    straightness = min(1.0, 4.0 * (0.5*(row_energy + col_energy)))

    maxc = np.maximum(np.maximum(R, G), B)
    minc = np.minimum(np.minimum(R, G), B)
    sat = np.where(maxc > 0, (maxc - minc) / (maxc + 1e-6), 0.0)
    mean_sat = float(np.mean(sat))
    greenish = (G > R) & (G > B) & (G > 0.28)
    brownish = (R > 0.28) & (G > 0.20) & (B < 0.38) & (R > B)
    outdoor_ratio = float((greenish | brownish).mean())

    forest_penalty = 0.0
    if outdoor_ratio > 0.20 and mean_sat > 0.30 and edge_density < 0.12:
        forest_penalty = min(0.06, 0.5*outdoor_ratio + 0.5*mean_sat)

    dark_ratio = float((gray < 0.28).mean())
    dark_mask = (gray[:H,:W] < 0.28)
    edge_mask = (mag > np.percentile(mag, 70))
    trash_cue = float((dark_mask & edge_mask).mean()) * 1.5

    ent = _image_entropy(arr)

    base = (
        0.30 * edge_density +
        0.18 * straightness +
        0.14 * outdoor_ratio +
        0.18 * dark_ratio +
        0.12 * ent +
        0.08 * trash_cue
    )
    base += 0.05 + HEURISTIC_BIAS
    if edge_density > 0.08 and dark_ratio > 0.18:
        base += 0.06

    score = max(HEURISTIC_FLOOR, min(1.0, base - forest_penalty))
    return float(score)

# ------------ Verifier -------------
class Verifier:
    def __init__(self):
        self.model_kind = "heuristic"
        self.onnx_sess = None
        self.onnx_input_name = None
        self.tf_model = None

        # figure out class_map path (env -> model_stem.json -> ai/class_map.json)
        self.valid_index = PV_VALID_CLASS_INDEX
        cm_path = CLASS_MAP_PATH_ENV
        if not cm_path:
            stem_guess = os.path.splitext(MODEL_PATH)[0] + ".json"
            if os.path.isfile(stem_guess):
                cm_path = stem_guess
            elif os.path.isfile("ai/class_map.json"):
                cm_path = "ai/class_map.json"

        try:
            if cm_path and os.path.isfile(cm_path):
                with open(cm_path, "r") as f:
                    cmap = json.load(f)  # e.g. {"0":"dirty_places","1":"invalid"}
                norm = {}
                for k, v in cmap.items():
                    try:
                        norm[int(k)] = str(v)
                    except Exception:
                        pass
                for i, name in sorted(norm.items()):
                    if name.lower() == "dirty_places":
                        self.valid_index = i
                        break
                print(f"[VERIFIER] class_map loaded from {cm_path}; valid_index={self.valid_index}")
            else:
                print(f"[VERIFIER] class_map not found; using PV_VALID_CLASS_INDEX={self.valid_index}")
        except Exception as e:
            print("[VERIFIER] class_map read error; using env index:", repr(e))

        # Prefer ONNX if available
        if ort is not None and os.path.isfile(MODEL_PATH) and MODEL_PATH.lower().endswith(".onnx"):
            try:
                so = ort.SessionOptions()
                self.onnx_sess = ort.InferenceSession(MODEL_PATH, sess_options=so, providers=["CPUExecutionProvider"])
                self.onnx_input_name = self.onnx_sess.get_inputs()[0].name
                self.model_kind = "onnx"
                print(f"[VERIFIER] ONNX model loaded: {MODEL_PATH}")
                return
            except Exception as e:
                print("[VERIFIER] ONNX load error, will try TF then heuristic:", repr(e))

        # Fallback: TensorFlow (if present and model path exists)
        if tf is not None and os.path.isfile(MODEL_PATH) and not MODEL_PATH.lower().endswith(".onnx"):
            try:
                self.tf_model = tf.keras.models.load_model(MODEL_PATH, compile=False)
                self.model_kind = "tf"
                print(f"[VERIFIER] TF/Keras model loaded: {MODEL_PATH}")
                return
            except Exception as e:
                print("[VERIFIER] TF load error, falling back to heuristic:", repr(e))

        # Last resort: heuristic only
        if self.model_kind == "heuristic":
            if ort is None and tf is None:
                print("[VERIFIER] No ONNX or TF available, using heuristic only.")
            else:
                print("[VERIFIER] Model not found, using heuristic only.")

    def _predict_rel(self, path: str) -> float:
        """Return relevance score [0..1] using ONNX or TF or heuristic."""
        # --- ONNX ---
        if self.model_kind == "onnx" and self.onnx_sess is not None:
            x = _prep(path)  # 0..255 float
            out = self.onnx_sess.run(None, {self.onnx_input_name: x})
            y = np.array(out[0]).reshape(-1)

            if y.size == 1:
                # binary head (sigmoid/logit); clamp safely
                val = float(y[0])
                # if it looks like logits, map via sigmoid
                if val < 0.0 or val > 1.0:
                    val = float(1.0 / (1.0 + np.exp(-val)))
                return float(np.clip(val, 0.0, 1.0))

            # multiclass: use the probability of the valid class directly
            probs = _softmax_np(y.astype(float))
            return float(probs[self.valid_index])

        # --- TF ---
        if self.model_kind == "tf" and self.tf_model is not None:
            x = _prep(path)
            y = np.array(self.tf_model.predict(x, verbose=0)).reshape(-1)

            if y.size == 1:
                val = float(y[0])
                if val < 0.0 or val > 1.0:
                    val = float(1.0 / (1.0 + np.exp(-val)))
                return float(np.clip(val, 0.0, 1.0))

            probs = _softmax_np(y.astype(float))
            return float(probs[self.valid_index])

        # --- Heuristic ---
        return simple_relevance_heuristic(path)

    def score(self, path, existing_phashes=None):
        # 1) Duplicate check
        ph = compute_phash(path)
        dupe_of = None
        if (not DISABLE_DUP_PENALTY) and existing_phashes:
            try:
                ph_obj = imagehash.hex_to_hash(ph)
                for sid, other in existing_phashes:
                    if other and (ph_obj - imagehash.hex_to_hash(other) <= DUP_DISTANCE):
                        dupe_of = sid
                        break
            except Exception:
                pass

        # 2) EXIF presence
        exif_ok = exif_time_okay(path)

        # 3) Relevance/auth
        rel = self._predict_rel(path)
        auth = 0.6 if exif_ok in (True, None) else 0.2

        dup_penalty = 0.0 if DISABLE_DUP_PENALTY else (DUP_PENALTY_VALUE if dupe_of is not None else 0.0)
        exif_bonus  = 0.08 if exif_ok else 0.0

        action_score = max(0.0, min(1.0, 0.55*rel + 0.30*auth + exif_bonus - dup_penalty))

        # You can rename this to "valid_report" if you prefer
        label = "valid_report" if action_score >= PV_ACTION_CUTOFF else "invalid"
        status = "AUTO_OK" if label == "valid_report" else "RECHECK"

        return {
            "phash": ph,
            "duplicate_of": dupe_of,
            "exif_time_ok": True if exif_ok else (False if exif_ok is False else None),
            "relevance_score": float(rel),
            "auth_score": float(auth),
            "action_score": float(action_score),
            "ai_label": label,
            "status": status,
            "model_version": MODEL_VERSION + f"_{self.model_kind}"
        }
