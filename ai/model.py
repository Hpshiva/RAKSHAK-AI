import open_clip
import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch
import yaml
import os
from PIL import Image


class Model:
    def __init__(self, settings_path: str = None):
        if settings_path is None:
            settings_path = os.path.join(os.path.dirname(__file__), "settings.yaml")
        with open(settings_path, "r") as file:
            self.settings = yaml.safe_load(file)

        # Initialize device
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )

        self.model_name = self.settings["model-settings"]["model-name"]
        self.pretrained = self.settings["model-settings"].get("pretrained", "openai")
        self.threshold = self.settings["model-settings"]["prediction-threshold"]

        # Load CLIP model
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name=self.model_name,
            pretrained=self.pretrained,
            device=self.device
        )
        self.tokenizer = open_clip.get_tokenizer(self.model_name)

        self.labels = self.settings["label-settings"]["labels"]
        self.default_label = self.settings["label-settings"]["default-label"]

        self.labels_prompt = [
            f"a photo of {label}"
            for label in self.labels
        ]

        self.text_features = self.vectorize_text(self.labels_prompt)

    @torch.inference_mode()
    def transform_image(self, image: np.ndarray) -> torch.Tensor:
        """Convert OpenCV image to CLIP input tensor."""
        pil_image = Image.fromarray(image).convert("RGB")
        tensor = self.preprocess(pil_image).unsqueeze(0).to(self.device)
        return tensor

    @torch.inference_mode()
    def tokenize(self, text: list[str]) -> torch.Tensor:
        """Tokenize text prompts."""
        return self.tokenizer(text).to(self.device)

    @torch.inference_mode()
    def vectorize_text(self, text: list[str]) -> torch.Tensor:
        """Generate CLIP text embeddings."""
        tokens = self.tokenize(text)
        return self.model.encode_text(tokens)

    @torch.inference_mode()
    def predict_(
        self,
        text_features: torch.Tensor,
        image_features: torch.Tensor,
    ):
        """Calculate similarity between image and text."""

        image_features = image_features / image_features.norm(
            dim=-1,
            keepdim=True
        )

        text_features = text_features / text_features.norm(
            dim=-1,
            keepdim=True
        )

        similarity = image_features @ text_features.T

        values, indices = similarity[0].topk(1)

        return values, indices

    @torch.inference_mode()
    def predict(self, image: np.ndarray) -> dict:
        """Predict violence label from image."""

        image_tensor = self.transform_image(image)

        image_features = self.model.encode_image(image_tensor)

        values, indices = self.predict_(
            self.text_features,
            image_features
        )

        label_index = indices[0].item()

        model_confidence = abs(values[0].item())

        label_text = self.default_label

        if model_confidence >= self.threshold:
            label_text = self.labels[label_index]

        return {
            "label": label_text,
            "confidence": model_confidence,
        }

    @staticmethod
    def plot_image(image: np.ndarray, title_text: str):
        """Display image."""

        plt.figure(figsize=(13, 13))
        plt.title(title_text)
        plt.axis("off")

        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        plt.imshow(image)
        plt.show()
