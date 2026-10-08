# Backward compatibility re-export
from app.routes.playlists import (
    folders_router as router,
    _sync_legacy_folders_if_needed,
    _get_playlist_cover as _get_folder_cover,
    serialize_playlist_summary as serialize_folder_summary,
    list_folders,
    create_folder,
    get_folder,
    update_folder,
    delete_folder,
    add_or_move_song_to_folder,
    remove_song_from_folder,
)

__all__ = [
    "router",
    "list_folders",
    "create_folder",
    "get_folder",
    "update_folder",
    "delete_folder",
    "add_or_move_song_to_folder",
    "remove_song_from_folder",
]
