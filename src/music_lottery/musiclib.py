import os
import re
from typing import Iterable

from .models import ConfigModel, MusicMeta
from tinytag import TinyTag


MUSIC_EXTS = (
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".wma",
    ".m4a",
    ".aiff",
    ".opus",
)


def walk_all_musicfiles(path: str):
    loca: dict[str, float] = {}
    for root, _, files in os.walk(path):
        for filename in files:
            if os.path.splitext(filename)[1].lower() in MUSIC_EXTS:
                file = os.path.join(root, filename)
                loca[file] = os.path.getmtime(file)
    return loca


def split_with_exclusions(input_string: str, delimiter: str, exclusions: Iterable[str]):
    exclusion_pattern = "|".join(map(re.escape, exclusions))
    pattern = rf"(?<!{exclusion_pattern}){re.escape(delimiter)}(?!{exclusion_pattern})"
    result = re.split(pattern, input_string)
    return result


class MetadataReader:
    def __init__(self, config: ConfigModel):
        self.config = config

    def handle_artist_field(self, artist_field: list[str]):
        if len(artist_field) == 1:
            artists = split_with_exclusions(
                artists[0], self.config.artists_split, self.config.artists_dont_split
            )
        return artist_field

    def read_metadata(self, path: str):
        tag = TinyTag.get(path, image=True)
        tagd = tag.as_dict()
        cover = None
        if _ := tag.images.any:
            cover = _.data
        return MusicMeta(
            title=tagd.pop("title", (None,))[0],
            artists=self.handle_artist_field(tagd.pop("artist", [])),
            album=tagd.pop("album", (None,))[0],
            cover=cover,
            albumartists=self.handle_artist_field(
                tagd.pop("albumartist", [])
            ),
            extra=tagd,
        )
