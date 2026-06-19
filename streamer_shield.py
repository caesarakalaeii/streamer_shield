"""Multi-feature scammer classifier.

A Keras functional model with three inputs whose preprocessing is baked into the
graph (so serving just passes near-raw values):

  * ``username`` : string -> char-level TextVectorization -> Embedding -> Conv1D
  * ``bio``      : string -> word-level TextVectorization -> Embedding -> Conv1D
  * ``numeric``  : float vector (see features.NUMERIC_FEATURE_NAMES) -> Normalization

The three branches are concatenated into a sigmoid scam probability.

Building/training requires TensorFlow (runs in the API Docker image, python:3.12).
``features.py`` stays TF-free so the bot can build the inputs without TensorFlow.
"""
from __future__ import annotations

from typing import List, Sequence

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

import features as feat

DEFAULT_MODEL_PATH = "streamershield.keras"

USERNAME_MAX_LEN = 30
BIO_MAX_TOKENS = 5000
BIO_SEQ_LEN = 40


def make_preprocessors(
    usernames: Sequence[str],
    bios: Sequence[str],
    numeric_matrix,
    username_max_len: int = USERNAME_MAX_LEN,
):
    """Create and adapt the three preprocessing layers on the training data."""
    username_vec = layers.TextVectorization(
        standardize=None,  # usernames are already cleaned by features.clean_username
        split="character",
        output_mode="int",
        output_sequence_length=username_max_len,
        name="username_vectorizer",
    )
    username_vec.adapt(list(usernames))

    bio_vec = layers.TextVectorization(
        max_tokens=BIO_MAX_TOKENS,
        standardize="lower_and_strip_punctuation",
        split="whitespace",
        output_mode="int",
        output_sequence_length=BIO_SEQ_LEN,
        name="bio_vectorizer",
    )
    bio_vec.adapt(list(bios))

    numeric_norm = layers.Normalization(axis=-1, name="numeric_norm")
    numeric_norm.adapt(numeric_matrix)
    return username_vec, bio_vec, numeric_norm


def build_model(username_vec, bio_vec, numeric_norm, num_numeric: int = feat.NUM_NUMERIC_FEATURES):
    username_in = keras.Input(shape=(1,), dtype=tf.string, name="username")
    bio_in = keras.Input(shape=(1,), dtype=tf.string, name="bio")
    numeric_in = keras.Input(shape=(num_numeric,), dtype=tf.float32, name="numeric")

    # Username char branch
    u = username_vec(username_in)
    u = layers.Embedding(username_vec.vocabulary_size() + 1, 32, name="username_embedding")(u)
    u = layers.Conv1D(32, 3, activation="relu")(u)
    u = layers.GlobalAveragePooling1D()(u)

    # Bio word branch
    b = bio_vec(bio_in)
    b = layers.Embedding(BIO_MAX_TOKENS + 1, 32, name="bio_embedding")(b)
    b = layers.Conv1D(32, 3, activation="relu")(b)
    b = layers.GlobalAveragePooling1D()(b)

    # Numeric branch
    n = numeric_norm(numeric_in)
    n = layers.Dense(16, activation="relu")(n)

    x = layers.Concatenate()([u, b, n])
    x = layers.Dense(32, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(1, activation="sigmoid", name="scam")(x)

    model = keras.Model(inputs=[username_in, bio_in, numeric_in], outputs=out)
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    return model


def inputs_to_tensors(model_inputs_list: List[dict]) -> dict:
    """Turn a list of ``features.build_model_inputs`` dicts into a batched tensor dict.

    String inputs are shaped (N, 1) to match the model's ``Input(shape=(1,))`` and
    fed as tf.string tensors (numpy unicode arrays are rejected by Keras)."""
    return {
        "username": tf.constant([[mi["username"]] for mi in model_inputs_list], dtype=tf.string),
        "bio": tf.constant([[mi["bio"]] for mi in model_inputs_list], dtype=tf.string),
        "numeric": tf.constant([mi["numeric"] for mi in model_inputs_list], dtype=tf.float32),
    }


class StreamerShield:
    """Serving wrapper: load a trained .keras model and score feature dicts."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        print(f"loading model from {model_path}")
        self.loaded_model = keras.models.load_model(model_path)

    def predict(self, model_inputs: dict) -> float:
        """Score a single ``features.build_model_inputs`` dict; returns P(scammer)."""
        x = inputs_to_tensors([model_inputs])
        return float(self.loaded_model(x, training=False).numpy()[0][0])

    def predict_from_fields(self, **raw_fields) -> float:
        return self.predict(feat.build_model_inputs(**raw_fields))
