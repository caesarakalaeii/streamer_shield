"""Train the multi-feature StreamerShield model.

Default run trains on the self-contained synthetic bootstrap dataset and writes
``streamershield.keras`` (the artifact baked into the API image). Once real data
has been collected, prefer ``train_from_db.py`` to retrain on labelled observations.

Runs in the API Docker image (TensorFlow). Example:
    python streamer_shield_train.py --epochs 15 --out streamershield.keras
"""
from __future__ import annotations

import argparse

import numpy as np

import features
import synthetic
from streamer_shield import DEFAULT_MODEL_PATH, build_model, inputs_to_tensors, make_preprocessors


def rows_to_arrays(rows: list[dict]):
    mis = [features.build_model_inputs(**{k: v for k, v in r.items() if k != "label"}) for r in rows]
    numeric = np.array([mi["numeric"] for mi in mis], dtype="float32")
    labels = np.array([r["label"] for r in rows], dtype="float32")
    return mis, numeric, labels


def train_from_rows(rows: list[dict], model_path: str = DEFAULT_MODEL_PATH, epochs: int = 15,
                    val_frac: float = 0.2, seed: int = 42, batch_size: int = 64):
    import tensorflow as tf

    mis, numeric, labels = rows_to_arrays(rows)
    n = len(rows)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    cut = int(n * (1 - val_frac))
    tr, va = idx[:cut], idx[cut:]

    uvec, bvec, nnorm = make_preprocessors(
        [mis[i]["username"] for i in tr], [mis[i]["bio"] for i in tr], numeric[tr]
    )
    model = build_model(uvec, bvec, nnorm)
    model.summary()

    early = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=3, restore_best_weights=True, verbose=1
    )
    model.fit(
        inputs_to_tensors([mis[i] for i in tr]),
        labels[tr],
        validation_data=(inputs_to_tensors([mis[i] for i in va]), labels[va]),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[early],
        verbose=2,
    )
    model.save(model_path)
    print(f"saved model to {model_path}")
    _smoke(model)
    return model


def _smoke(model):
    """Eyeball a couple of obvious cases."""
    scam = features.build_model_inputs(
        login="jessica_howard472", description="FREE gift cards discord.gg/x",
        account_age_days=3, broadcaster_type="", profile_image_url=synthetic._DEFAULT_AVATAR,
    )
    human = features.build_model_inputs(
        login="caesarlp", description="variety streamer, souls games", account_age_days=2200,
        broadcaster_type="partner", follower_count=12000,
        profile_image_url="https://static-cdn.jtvnw.net/jtv_user_pictures/real.png",
    )
    x = inputs_to_tensors([scam, human])
    preds = model(x, training=False).numpy().ravel()
    print(f"smoke: scammer-like={preds[0]:.3f}  human-like={preds[1]:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_MODEL_PATH)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--n-per-class", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rows = synthetic.generate(n_per_class=args.n_per_class, seed=args.seed)
    print(f"training on {len(rows)} synthetic rows")
    train_from_rows(rows, model_path=args.out, epochs=args.epochs, seed=args.seed)


if __name__ == "__main__":
    main()
