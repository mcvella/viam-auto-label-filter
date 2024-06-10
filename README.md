# auto-label-filter modular resource

This module implements the [rdk camera API](https://github.com/rdk/camera-api) in a mcvella:camera:auto-label-filter model.
With this model you can leverage a configured detector, as well as an optional VLM set up as a classifier (for example [Moondream](https://app.viam.com/module/mcvella/moondream-vision-modal)) to automatically capture labeled training images with bounding boxes.

For example, if you wanted to train an ML model to detect specific household pets, you could first set up a detector like [Grounding Dino](https://app.viam.com/module/mcvella/grounding-dino) that knows how to spot cats and dogs.
Then, you can set up a VLM classifier like [Moondream](https://app.viam.com/module/mcvella/moondream-vision-modal), which can more specifically label dog and cat detections.
You can then configure this module like:

``` json
{
  "detector": "grounding-dino",
  "classifier": "moondream",
  "dataset_name": "pets",
  "labels": [
    { "match": "white dog with spots", "label": "fido"},
    { "match": "brown furry dog", "label": "rex"},
    { "match": "black cat", "label": "onyx"},
    { "match": "calico cat", "label": "lemeaux"}
  ]
}
```

Now, any images that have detections that match will be stored in the *pets* dataset in [Viam Data Management](https://docs.viam.com/services/data/).

## Requirements

At minimum, a CV detector must be set up in your Viam machine.
It is recommended that a grounding model like [Grounding Dino](https://app.viam.com/module/mcvella/grounding-dino) be used, as it can match a large number of "base" classes, and will do partial matches (like matching "person" in "person wearing glasses").

A VLM-based classifier like [Moondream](https://app.viam.com/module/mcvella/moondream-vision-modal) is not required, but if you want accurate matches on more complex classes like "person wearing glasses" or "brown furry dog" you'll need it set up.
Note that running these models can be taxing on CPUs/GPUs, and you'll need to consider this when setting up data capture (you may only be able to capture data at rate of one image every 5-30 seconds, depending on the hardware the VLM is running on).

Both the detector and classifier would be configured as dependencies of this camera model.

## Build and run

To use this module, follow the instructions to [add a module from the Viam Registry](https://docs.viam.com/registry/configure/#add-a-modular-resource-from-the-viam-registry) and select the `rdk:camera:mcvella:camera:auto-label-filter` model from the [`mcvella:camera:auto-label-filter` module](https://app.viam.com/module/rdk/mcvella:camera:auto-label-filter).

## Configure your camera

> [!NOTE]  
> Before configuring your camera, you must [create a machine](https://docs.viam.com/manage/fleet/machines/#add-a-new-machine).

Navigate to the **Config** tab of your machine's page in [the Viam app](https://app.viam.com/).
Click on the **Components** subtab and click **Create component**.
Select the `camera` type, then select the `mcvella:camera:auto-label-filter` model.
Click **Add module**, then enter a name for your camera and click **Create**.

On the new component panel, copy and paste the following attribute template into your camera’s **Attributes** box:

```json
{
  "detector": "grounding-dino",
  "classifier": "moondream",
  "camera": "physical-camera",
  "labels": [
    "person without glasses",
    { "match": "person with glasses", "label": "wearing glasses" }
  ],
  "dataset_name": "glasses",
  "detector_confidence_threshold": 0.4,
  "org_id": "abc123",
  "location_id": "xyz213",
  "part_id": "mhj127",
  "app_api_key": "my_app_key",
  "app_api_key_id": "my_api_key_id",
}
```

> [!NOTE]  
> For more information, see [Configure a Machine](https://docs.viam.com/manage/configuration/).

### Attributes

The following attributes are available for `rdk:camera:mcvella:camera:auto-label-filter` cameras:

| Name | Type | Inclusion | Description |
| ---- | ---- | --------- | ----------- |
| `detector` | string | **Required** |  Name of configured detector |
| `classifier` | string | Optional |  Name of configured VLM classifier - must accept "question" as an extra parameter |
| `camera` | string | **Required** |  Name of physical camera to capture images |
| `labels` | list | **Required** |  List of labels to auto-detect and label. Labels can be a string representing the label or a dictionary in the form of {"match": "thing to detect", "label": "what to label it"} |
| `dataset_name` | string | Optional |  Name of dataset to associate captured images with, if specified. Will create the dataset if it does not yet exist. |
| `detector_confidence_threshold` | float | Optional |  Minimum confidence for detections, defaults to 0.4. |
| `org_id` | string | **Required** |  Viam organization ID in which to store data |
| `location_id` | string | **Required** |  Viam location ID for which to store data |
| `part_id` | string | **Required** |  Viam location ID for which to store data |
| `app_api_key` | string | **Required** |  Viam app API key to use to store data in the Viam cloud |
| `app_api_key_id` | string | **Required** |  Viam app API key ID to use to store data in the Viam cloud |
