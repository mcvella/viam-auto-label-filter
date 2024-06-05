from typing import ClassVar, Mapping, Sequence, Any, Dict, Optional, Tuple, Final, List, cast
from typing_extensions import Self

import sys
from typing import Any, Dict, Final, List, Optional, Tuple
from PIL import ImageDraw

from viam.media.video import NamedImage, ViamImage
from viam.proto.common import ResponseMetadata
from viam.proto.component.camera import GetPropertiesResponse

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

from viam.module.types import Reconfigurable
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName, Vector3
from viam.resource.base import ResourceBase
from viam.resource.types import Model, ModelFamily

from viam.components.camera import Camera
from viam.services.vision import VisionClient
from viam.errors import NoCaptureToStoreError
from viam.utils import from_dm_from_extra
from viam.media.utils.pil import viam_to_pil_image, pil_to_viam_image, CameraMimeType

from viam.logging import getLogger

import re

LOGGER = getLogger(__name__)

class autoLabelFilter(Camera, Reconfigurable):
    
    """
    Camera represents any physical hardware that can capture frames.
    """
    Properties: "TypeAlias" = GetPropertiesResponse
    

    MODEL: ClassVar[Model] = Model(ModelFamily("mcvella", "camera"), "auto-label-filter")
    camera_properties: Camera.Properties = Properties()
    camera: Camera
    detector: VisionClient
    classifier: None
    label_map: Dict = {}
    label_query: str = ""
    detector_label_type: str
    detector_confidence_threshold: float

    # Constructor
    @classmethod
    def new(cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]) -> Self:
        my_class = cls(config.name)
        my_class.reconfigure(config, dependencies)
        return my_class

    @classmethod
    def validate(cls, config: ComponentConfig):
        actual_cam = config.attributes.fields["camera"].string_value
        if actual_cam == "":
            raise Exception("camera attribute is required")
        detector = config.attributes.fields["detector"].string_value
        if detector == "":
            raise Exception("detector attribute is required")
        labels = config.attributes.fields["labels"].list_value or []
        if len(labels) < 1:
            raise Exception("labels at least one label is required")
        return

    def reconfigure(self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]):
        camera = config.attributes.fields["camera"].string_value
        actual_camera = dependencies[Camera.get_resource_name(camera)]
        self.camera = cast(Camera, actual_camera)
        
        detector = config.attributes.fields["detector"].string_value
        actual_detector = dependencies[VisionClient.get_resource_name(detector)]
        self.detector = cast(VisionClient, actual_detector)

        classifier = config.attributes.fields["classifier"].string_value or ""
        if (classifier != ""):
            actual_classifier= dependencies[VisionClient.get_resource_name(classifier)]
            self.classifier = cast(VisionClient, actual_classifier)

        self.label_map = {}
        self.label_query = ""
        labels = config.attributes.fields["labels"].list_value
        for label in labels:
            if isinstance(label, dict):
                self.label_map[label["key"]] = label["value"]
                self.label_query = self.label_query + f"{label["key"]}. "
            else:
                self.label_map[label] = label
                self.label_query = self.label_query + f"{label}. "
        
        # should be "filter" or "query"
        self.detector_label_type = config.attributes.fields["detector_label_type"].string_value or "query"
        
        self.detector_confidence_threshold = config.attributes.fields["detector_confidence_threshold"].number_value or .4

    def questions_from_class(self, class_name):
        class_name = class_name.replace("a ", "")
        classes = re.split('\s', class_name)
        questions = []
        for label in self.label_map.keys():
            for c in classes:
                if c in label:
                    questions.append({ "label": label, "question": f"is this {label} - answer yes or no" })
        return questions

    async def get_image(
        self, mime_type: str = "", *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None, **kwargs
    ) -> ViamImage:
        cam_image = await self.camera.get_image(mime_type="image/jpeg")

        detections = []

        LOGGER.error(self.label_query)
        if self.detector_label_type == "query":
            # use query-style classes as per detectors like grounding-dino
            udetections = await self.detector.get_detections(cam_image, extra={"query": self.label_query})
            LOGGER.error(udetections)
            for detection in udetections:
                if detection.confidence >= self.detector_confidence_threshold:
                    detections.append(detection)
        else:
            udetections = await self.detector.get_detections(cam_image)
            # filter for wanted classes
            for detection in udetections:
                if detection.confidence >= self.detector_confidence_threshold and detection['class_name'] in self.label_map.keys():
                    detections.append(detection)

        LOGGER.error(detections)

        im = viam_to_pil_image(cam_image)
        
        if hasattr(self, "classifier"):
            verified_detections = []
            for detection in detections:
                questions = self.questions_from_class(detection.class_name)
                if len(questions) > 0:
                    cropped = im.crop((detection.x_min, detection.y_min, detection.x_max, detection.y_max))
                    for question in questions:
                        LOGGER.error(question["question"])
                        classifications = await self.classifier.get_classifications(pil_to_viam_image(cropped, CameraMimeType.JPEG), 1, extra={"question": question["question"]})
                        LOGGER.error(classifications)
                        if len(classifications) and ''.join(classifications[0].class_name.split()).lower() == 'yes':
                            detection.class_name = self.label_map[question["label"]]
                            verified_detections.append(detection)
            detections = verified_detections

        if from_dm_from_extra(extra):
            raise NoCaptureToStoreError()

        # add bounding boxes to image for testing (when not called from data management)
        draw = ImageDraw.Draw(im)

        for d in detections:
            draw.rectangle(((d.x_min, d.y_min), (d.x_max, d.y_max)), outline="red")
            draw.text((d.x_min + 10, d.y_min), d.class_name, fill="red")

        return pil_to_viam_image(im, CameraMimeType.JPEG)
    
    async def get_images(self, *, timeout: Optional[float] = None, **kwargs) -> Tuple[List[NamedImage], ResponseMetadata]:
        raise NotImplementedError


    
    async def get_point_cloud(
        self, *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None, **kwargs
    ) -> Tuple[bytes, str]:
        raise NotImplementedError


    
    async def get_properties(self, *, timeout: Optional[float] = None, **kwargs) -> Properties:
        return self.camera_properties

