import open_clip
import cv2
import numpy as np
import torch
import yaml
import os
from PIL import Image

# Keep the two simultaneous AI workers from consuming every CPU thread and
# starving video decoding/JPEG streaming on CPU-only systems.
CPU_TORCH_THREADS = None
if not torch.cuda.is_available():
    # ViT-L becomes slower on this workload when PyTorch oversubscribes CPU
    # cores alongside video decoding and YOLO. Four threads measured best on
    # the target 12-thread CPU and can still be overridden for other hosts.
    torch_threads = int(os.environ.get("RAKSHAK_TORCH_THREADS", "4"))
    CPU_TORCH_THREADS = max(1, min(torch_threads, os.cpu_count() or 4))
    torch.set_num_threads(CPU_TORCH_THREADS)
    cv2.setNumThreads(2)


# Prompt ensembling: score each label against several phrasings instead of
# one and average the (renormalized) text embeddings. This is a standard
# zero-shot CLIP accuracy technique (used in the original CLIP paper) that
# typically improves zero-shot accuracy a few points with zero extra
# per-frame cost, since text embeddings are only computed once at startup.
#
# IMPORTANT: changing the prompts shifts the similarity-score distribution,
# so the empirically-tuned thresholds in ai/detector.py (VIOLENCE_SCORE_
# THRESHOLD, VIOLENCE_INSTANT_THRESHOLD, WEAPON_*_CROP_THRESHOLD) should be
# re-validated against evaluation/benchmark.py on real footage before this
# is relied on in production. They were tuned against the single-template
# prompts this replaces.
PROMPT_TEMPLATES = [
    "a photo of {}",
    "a security camera photo of {}",
    "CCTV footage showing {}",
    "a low quality surveillance image of {}",
    "a photo of a person during {}",
]


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
        self.threshold = self.settings["model-settings"]["prediction-threshold"]

        # Load CLIP model
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name=self.model_name,
            pretrained="openai",
            device=self.device
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(self.model_name)

        self.labels = self.settings["label-settings"]["labels"]
        self.default_label = self.settings["label-settings"]["default-label"]

        self.labels_prompt = [
            [template.format(label) for template in PROMPT_TEMPLATES]
            for label in self.labels
        ]

        self.text_features = self._vectorize_ensembled_prompts(self.labels_prompt)

    def _restore_cpu_threads(self):
        """Undo thread-pool changes made by the Ultralytics CPU predictor."""
        if CPU_TORCH_THREADS and torch.get_num_threads() != CPU_TORCH_THREADS:
            torch.set_num_threads(CPU_TORCH_THREADS)

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
    def _vectorize_ensembled_prompts(self, grouped_prompts: list[list[str]]) -> torch.Tensor:
        """Encode several prompt templates per label, average the
        normalized embeddings, and renormalize (CLIP prompt ensembling).
        Runs once at startup, so it adds no per-frame inference cost.
        """
        prompts_per_label = len(grouped_prompts[0])
        flat_prompts = [prompt for prompts in grouped_prompts for prompt in prompts]
        flat_features = self.vectorize_text(flat_prompts)
        flat_features = flat_features / flat_features.norm(dim=-1, keepdim=True)
        per_label = flat_features.view(len(grouped_prompts), prompts_per_label, -1)
        averaged = per_label.mean(dim=1)
        return averaged / averaged.norm(dim=-1, keepdim=True)

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

        self._restore_cpu_threads()

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

    @torch.inference_mode()
    def predict_scores(self, image: np.ndarray) -> dict[str, float]:
        """Return normalized CLIP similarity scores for every configured label."""
        self._restore_cpu_threads()
        image_features = self.model.encode_image(self.transform_image(image))
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        similarities = (image_features @ self.text_features.T)[0]
        return {
            label: float(similarities[index].item())
            for index, label in enumerate(self.labels)
        }

    @torch.inference_mode()
    def predict_batch_scores(self, images: list[np.ndarray]) -> list[dict[str, float]]:
        """Classify multiple frames/crops in one model pass for lower latency."""
        if not images:
            return []
        self._restore_cpu_threads()
        tensors = torch.cat([self.transform_image(image) for image in images], dim=0)
        image_features = self.model.encode_image(tensors)
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        similarities = image_features @ self.text_features.T
        return [
            {
                label: float(row[index].item())
                for index, label in enumerate(self.labels)
            }
            for row in similarities
        ]
