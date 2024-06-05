"""
This file registers the model with the Python SDK.
"""

from viam.components.camera import Camera
from viam.resource.registry import Registry, ResourceCreatorRegistration

from .autoLabelFilter import autoLabelFilter

Registry.register_resource_creator(Camera.SUBTYPE, autoLabelFilter.MODEL, ResourceCreatorRegistration(autoLabelFilter.new, autoLabelFilter.validate))
