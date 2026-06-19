"""StreamerShield prediction API.

Accepts the multi-feature payload (built from a Twitch user by the bot) and returns
the scam probability. Preprocessing is baked into the model, so this process only
needs the raw fields + features.build_model_inputs.

Returns ``result`` as a 0..1 float (the legacy API returned prob*1000).
"""
import os

from flask import Flask, jsonify, request

import features
from streamer_shield import DEFAULT_MODEL_PATH, StreamerShield

app = Flask(__name__)

MODEL_PATH = os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)
try:
    shield = StreamerShield(MODEL_PATH)
except Exception as exc:  # noqa: BLE001 - surface load failure via /health, let k8s restart
    print(f"FATAL: could not load model {MODEL_PATH}: {exc}")
    shield = None


@app.route("/health")
def health():
    if shield is not None and getattr(shield, "loaded_model", None) is not None:
        return ("", 200)
    return ("model not loaded", 503)


@app.route("/api/predict", methods=["POST"])
def predict():
    if shield is None:
        return jsonify({"error": "model not loaded"}), 503
    try:
        data = request.get_json(force=True) or {}
        model_inputs = features.build_model_inputs(
            login=data["login"],
            display_name=data.get("display_name"),
            description=data.get("description"),
            account_age_days=float(data.get("account_age_days", 0.0) or 0.0),
            follower_count=data.get("follower_count"),
            follows_channel=data.get("follows_channel"),
            follow_age_days=data.get("follow_age_days"),
            broadcaster_type=data.get("broadcaster_type"),
            profile_image_url=data.get("profile_image_url"),
            has_default_avatar_value=data.get("has_default_avatar"),
        )
        prob = shield.predict(model_inputs)
        return jsonify({"result": prob, "action_hint": _action_hint(prob)})
    except KeyError as exc:
        return jsonify({"error": f"missing field: {exc}"}), 400
    except Exception as exc:  # noqa: BLE001
        print(exc)
        return jsonify({"error": str(exc)}), 400


def _action_hint(prob: float) -> str:
    """Informational only; the bot makes the real decision with its own thresholds."""
    if prob >= 0.9:
        return "RESTRICTED"
    if prob >= 0.5:
        return "ACTIVE_MONITORING"
    return "NONE"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 38080)))
