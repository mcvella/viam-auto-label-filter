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

from viam.proto.app.data import BinaryID
from viam.components.camera import Camera
from viam.services.vision import VisionClient
from viam.errors import NoCaptureToStoreError
from viam.utils import from_dm_from_extra
from viam.media.utils.pil import viam_to_pil_image, pil_to_viam_image, CameraMimeType
from viam.app.data_client import DataClient
from viam.app.viam_client import ViamClient
from viam.rpc.dial import Credentials, DialOptions
from viam.robot.service import RobotService
from viam.logging import getLogger

import re
import io
import asyncio

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

    app_client : None
    api_key_id: str
    api_key: str
    part_id: str
    location_id: str
    org_id: str
    dataset_name: str = ""
    dataset_id: str = ""

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
        
        api_key = config.attributes.fields["app_api_key"].string_value
        if api_key == "":
            raise Exception("app_api_key attribute is required")
        api_key_id = config.attributes.fields["app_api_key_id"].string_value
        if api_key_id == "":
            raise Exception("app_api_key_id attribute is required")
        part_id = config.attributes.fields["part_id"].string_value
        if part_id == "":
            raise Exception("part_id attribute is required")
        location_id = config.attributes.fields["location_id"].string_value
        if location_id == "":
            raise Exception("location_id attribute is required")
        org_id = config.attributes.fields["org_id"].string_value
        if org_id == "":
            raise Exception("org_id attribute is required")
        return

    async def viam_connect(self) -> ViamClient:
        dial_options = DialOptions.with_api_key( 
            api_key=self.api_key,
            api_key_id=self.api_key_id
        )
        return await ViamClient.create_from_dial_options(dial_options)

    async def get_dataset_id(self) -> str:
        datasets = await self.app_client.data_client.list_datasets_by_organization_id(self.org_id)
        dataset_id = ""
        for dataset in datasets:
            if dataset.name == self.dataset_name:
                dataset_id = dataset.id
        # if no match, create a new one
        if dataset_id == "":
            dataset_id = await self.app_client.data_client.create_dataset(name=self.dataset_name, organization_id=self.org_id)
        return dataset_id
    
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
                self.label_map[label["match"]] = label["label"]
                self.label_query = self.label_query + f"{label["match"]}. "
            else:
                self.label_map[label] = label
                self.label_query = self.label_query + f"{label}. "
        
        # should be "filter" or "query"
        self.detector_label_type = config.attributes.fields["detector_label_type"].string_value or "query"
        
        self.detector_confidence_threshold = config.attributes.fields["detector_confidence_threshold"].number_value or .4

        self.api_key = config.attributes.fields["app_api_key"].string_value
        self.api_key_id = config.attributes.fields["app_api_key_id"].string_value
        self.part_id = config.attributes.fields["part_id"].string_value
        self.location_id = config.attributes.fields["location_id"].string_value
        self.org_id = config.attributes.fields["org_id"].string_value
        self.dataset_name = config.attributes.fields["dataset_name"].string_value or ""

    def questions_from_class(self, class_name):
        class_name = class_name.replace("a ", "")
        classes = re.split('\s', class_name)
        questions = []
        seen_questions = {}
        for label in self.label_map.keys():
            for c in classes:
                if c in label:
                    question = f"is this {label} - answer yes or no"
                    if not label + question in seen_questions:
                        questions.append({ "label": label, "question": question })
                        seen_questions[label + question] = True
        return questions

    async def get_image(
        self, mime_type: str = "", *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None, **kwargs
    ) -> ViamImage:
        cam_image = await self.camera.get_image(mime_type="image/jpeg")

        detections = []

        if self.detector_label_type == "query":
            # use query-style classes as per detectors like grounding-dino
            udetections = await self.detector.get_detections(cam_image, extra={"query": self.label_query})
            for detection in udetections:
                if detection.confidence >= self.detector_confidence_threshold:
                    detections.append(detection)
        else:
            udetections = await self.detector.get_detections(cam_image)
            # filter for wanted classes
            for detection in udetections:
                if detection.confidence >= self.detector_confidence_threshold and detection['class_name'] in self.label_map.keys():
                    detections.append(detection)

        im = viam_to_pil_image(cam_image)
        
        verified_detections = []

        if hasattr(self, "classifier"):
            verified_detections = []
            classify_tasks = []
            classified_keys = {}
            qs = []
            for detection in detections:
                questions = self.questions_from_class(detection.class_name)
                if len(questions) > 0:
                    cropped = im.crop((detection.x_min, detection.y_min, detection.x_max, detection.y_max))
                    for question in questions:
                        question["detection"] = detection
                        # ensure there are no repeat queries for the same
                        key = str(detection.x_min) + str(detection.y_min) + str(detection.x_max) + str(detection.y_max) + question["question"]
                        if not key in classified_keys:
                            qs.append(question)
                            classify_tasks.append(self.classifier.get_classifications(pil_to_viam_image(cropped, CameraMimeType.JPEG), 1, extra={"question": question["question"]}))
                            classified_keys[key] = True
            results = await asyncio.gather(*classify_tasks)
            q_index = 0
            for classifications in results:
                question = qs[q_index]
                if len(classifications) and ''.join(classifications[0].class_name.split()).lower() == 'yes':
                    question["detection"].class_name = self.label_map[question["label"]]
                    verified_detections.append(question["detection"])
                q_index = q_index + 1
        else:
            verified_detections = detections

        if from_dm_from_extra(extra):
            if not hasattr(self, "app_client"):
                # auth to cloud for data storage
                self.app_client = await self.viam_connect()
            if self.dataset_name != "" and self.dataset_id == "":
                # get dataset id from name
                self.dataset_id = await self.get_dataset_id()

            for d in verified_detections:
                buf = io.BytesIO()
                im.save(buf, format='JPEG')
                img_id = await self.app_client.data_client.file_upload(part_id=self.part_id, file_extension=".jpg", data=buf.getvalue())
                binary_id = BinaryID(
                    file_id=img_id,
                    organization_id=self.org_id,
                    location_id=self.location_id
                )
                width, height = im.size
                await self.app_client.data_client.add_bounding_box_to_image_by_id(
                    binary_id=binary_id,
                    label=detection.class_name,
                    x_min_normalized=detection.x_min/width,
                    y_min_normalized=detection.y_min/height,
                    x_max_normalized=detection.x_max/width,
                    y_max_normalized=detection.y_max/height
                )
                if self.dataset_id != "":
                    binary_ids = []
                    binary_ids.append(binary_id)
                    await self.app_client.data_client.add_binary_data_to_dataset_by_ids(binary_ids=binary_ids, dataset_id=self.dataset_id)

            # are using data management for scheduling the capture but not cloud sync,
            # as storing bounding boxes this way is not yet supported.
            raise NoCaptureToStoreError()
        else:
            # add bounding boxes to image for testing (when not called from data management)
            draw = ImageDraw.Draw(im)

            for d in verified_detections:
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

