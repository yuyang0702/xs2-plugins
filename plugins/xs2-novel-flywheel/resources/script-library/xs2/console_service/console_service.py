"""Novel workbench business capabilities, loaded by the enabled plugin owner."""
from . import configuration
from . import production
from .assistant import NovelAssistantJobs, _receive_model_reply
from .adoption import ReferenceAdoptionJobs
from .library_metadata import library_metadata


def create_assistant(model_factory, support_loader, catalog_loader=None):
    return NovelAssistantJobs(model_factory, support_loader, catalog_loader=catalog_loader)
