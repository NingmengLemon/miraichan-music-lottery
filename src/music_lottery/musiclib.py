import json
import os
import posixpath
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
            if posixpath.splitext(filename)[1].lower() in MUSIC_EXTS:
                file = posixpath.join(root, filename).replace("\\", "/")
                loca[file] = posixpath.getmtime(file)
    return loca


def split_with_exclusions(
    input_string: str,
    delimiter: str,
    exclusions: Iterable[str] = None,
    ignore_case: bool = False,
) -> list[str]:
    inputs = input_string.split(delimiter)
    if not exclusions:
        return inputs
    excs = {i.lower() for i in exclusions} if ignore_case else set(exclusions)
    result = []
    i = 0
    while i < len(inputs):
        if (
            i + 1 < len(inputs)
            and (str.lower if ignore_case else lambda x: x)(
                exc := (inputs[i] + delimiter + inputs[i + 1])
            )
            in excs
        ):
            result.append(exc)
            i += 1
        else:
            result.append(inputs[i])
        i += 1
    return result


class MetadataReader:
    def __init__(self, config: ConfigModel):
        self.config = config

    def handle_artist_field(self, artist_field: list[str]):
        if len(artist_field) != 1:
            return artist_field
        for split in self.config.artists_split:
            if (
                len(
                    result := split_with_exclusions(
                        artist_field[0],
                        split,
                        self.config.artists_dont_split,
                    )
                )
                > 1
            ):
                return result

    def read_metadata(self, path: str):
        tag = TinyTag.get(path, image=False)
        tagd = tag.as_dict()
        return MusicMeta(
            title=tagd.pop("title", (None,))[0],
            album=tagd.pop("album", (None,))[0],
            artists=json.dumps(
                self.handle_artist_field(tagd.pop("artist", [])), ensure_ascii=False
            ),
            albumartists=json.dumps(
                self.handle_artist_field(tagd.pop("albumartist", [])),
                ensure_ascii=False,
            ),
            duration=tagd.get("duration", 0),
        )
