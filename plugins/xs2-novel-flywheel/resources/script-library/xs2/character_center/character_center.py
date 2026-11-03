"""Character workbench read, preview, publication and history entry points."""
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'character_center'

from .cards import inventory, link_relations, workspace
from .edits import apply, history, preview
from .states import add_state
from .assistant_hooks import accept_trial, finish, freeze, is_current, planned_preferences, trial_preferences


def read(root, chapter='', q=''):
    root = workspace(root)
    view, _, _ = inventory(root)
    add_state(root, view, chapter)
    link_relations(view['characters'])
    query = q.strip().casefold()
    if query:
        view['characters'] = [row for row in view['characters']
                              if query in row['name'].casefold() or query in row['title'].casefold()
                              or any(query in raw['text'].casefold() for raw in row['raw'])]
    return view
