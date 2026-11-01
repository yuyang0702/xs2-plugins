"""Novel workbench business capabilities, loaded by the enabled plugin owner."""
from . import configuration
from . import production
from .assistant import NovelAssistantJobs, _receive_model_reply


def create_assistant(model_factory, support_loader):
    return NovelAssistantJobs(model_factory, support_loader)
