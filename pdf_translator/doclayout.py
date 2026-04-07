"""DocLayout-YOLO model for document layout detection.

Adapted from scholar-translator. Detects text regions, formulas, figures,
and tables in PDF page images using an ONNX model.
"""

import abc
import os.path

import cv2
import numpy as np
import ast
from babeldoc.assets.assets import get_doclayout_onnx_model_path

try:
    import onnx
    import onnxruntime
except ImportError as e:
    if "DLL load failed" in str(e):
        raise OSError(
            "Microsoft Visual C++ Redistributable is not installed. "
            "Download it at https://aka.ms/vs/17/release/vc_redist.x64.exe"
        ) from e
    raise

from huggingface_hub import hf_hub_download


class DocLayoutModel(abc.ABC):
    @staticmethod
    def load_onnx():
        return OnnxModel.from_pretrained()

    @staticmethod
    def load_available():
        return DocLayoutModel.load_onnx()

    @property
    @abc.abstractmethod
    def stride(self) -> int:
        pass

    @abc.abstractmethod
    def predict(self, image, imgsz=1024, **kwargs) -> list:
        pass


class YoloResult:
    def __init__(self, boxes, names):
        self.boxes = [YoloBox(data=d) for d in boxes]
        self.boxes.sort(key=lambda x: x.conf, reverse=True)
        self.names = names


class YoloBox:
    def __init__(self, data):
        self.xyxy = data[:4]
        self.conf = data[-2]
        self.cls = data[-1]


class OnnxModel(DocLayoutModel):
    def __init__(self, model_path: str):
        self.model_path = model_path
        model = onnx.load(model_path)
        metadata = {d.key: d.value for d in model.metadata_props}
        # ast.literal_eval is safe — only parses Python literals, not arbitrary code
        self._stride = ast.literal_eval(metadata["stride"])
        self._names = ast.literal_eval(metadata["names"])
        self.model = onnxruntime.InferenceSession(model.SerializeToString())

    @staticmethod
    def from_pretrained():
        pth = get_doclayout_onnx_model_path()
        return OnnxModel(pth)

    @property
    def stride(self):
        return self._stride

    def resize_and_pad_image(self, image, new_shape):
        if isinstance(new_shape, int):
            new_shape = (new_shape, new_shape)
        h, w = image.shape[:2]
        new_h, new_w = new_shape
        r = min(new_h / h, new_w / w)
        resized_h, resized_w = int(round(h * r)), int(round(w * r))
        image = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
        pad_w = (new_w - resized_w) % self.stride
        pad_h = (new_h - resized_h) % self.stride
        top, bottom = pad_h // 2, pad_h - pad_h // 2
        left, right = pad_w // 2, pad_w - pad_w // 2
        image = cv2.copyMakeBorder(
            image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
        )
        return image

    def scale_boxes(self, img1_shape, boxes, img0_shape):
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])
        pad_x = round((img1_shape[1] - img0_shape[1] * gain) / 2 - 0.1)
        pad_y = round((img1_shape[0] - img0_shape[0] * gain) / 2 - 0.1)
        boxes[..., :4] = (boxes[..., :4] - [pad_x, pad_y, pad_x, pad_y]) / gain
        return boxes

    def predict(self, image, imgsz=1024, **kwargs):
        orig_h, orig_w = image.shape[:2]
        pix = self.resize_and_pad_image(image, new_shape=imgsz)
        pix = np.transpose(pix, (2, 0, 1))
        pix = np.expand_dims(pix, axis=0)
        pix = pix.astype(np.float32) / 255.0
        new_h, new_w = pix.shape[2:]
        preds = self.model.run(None, {"images": pix})[0]
        preds = preds[preds[..., 4] > 0.25]
        preds[..., :4] = self.scale_boxes(
            (new_h, new_w), preds[..., :4], (orig_h, orig_w)
        )
        return [YoloResult(boxes=preds, names=self._names)]


class ModelInstance:
    value: OnnxModel = None
