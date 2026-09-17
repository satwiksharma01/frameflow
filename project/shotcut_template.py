#!/usr/bin/env python3
"""The Shotcut-specific scaffolding an MLT file needs to open as a project.

Phase 0 established that a file can be perfectly valid MLT - the `melt` engine
loads and plays it - and still open in Shotcut's UI as a single previewable
clip rather than an editable timeline. Shotcut's project loader keys off
conventions layered on top of the MLT spec. This module is the single
definition of those conventions, used by the compiler to write them and by the
parser to recognise and skip them.

Do not trim these elements for tidiness: each one was empirically required.
"""
import xml.etree.ElementTree as ET

SHOTCUT_TITLE = "Shotcut version 26.8.1"
MLT_VERSION = "7.9.0"

MAIN_BIN_ID = "main_bin"
BLACK_PRODUCER_ID = "black"
BACKGROUND_PLAYLIST_ID = "background"
TRACTOR_ID = "tractor0"

# Frameflow's own metadata, namespaced so it cannot collide with shotcut:*.
# MLT has nowhere to record these concepts, so we attach them as custom
# properties - whether Shotcut preserves them across a human save is an open
# empirical question (see the Milestone 2 round-trip test).
PROVENANCE_PROPERTY = "frameflow:source_frame_rate_mode"
TRACK_TYPE_PROPERTY = "frameflow:track_type"


def _prop(parent: ET.Element, name: str, value: str) -> None:
    ET.SubElement(parent, "property", {"name": name}).text = value


def build_root(width: int, height: int, fps_num: int, fps_den: int,
               dar_num: int, dar_den: int) -> ET.Element:
    """The <mlt> root, its <profile>, and the main_bin media pool."""
    mlt = ET.Element("mlt", {
        "LC_NUMERIC": "C",
        "version": MLT_VERSION,
        "title": SHOTCUT_TITLE,
        "producer": MAIN_BIN_ID,
    })
    ET.SubElement(mlt, "profile", {
        "description": "frameflow-auto",
        "width": str(width),
        "height": str(height),
        "progressive": "1",
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "display_aspect_num": str(dar_num),
        "display_aspect_den": str(dar_den),
        "frame_rate_num": str(fps_num),
        "frame_rate_den": str(fps_den),
        "colorspace": "709",
    })
    main_bin = ET.SubElement(mlt, "playlist", {"id": MAIN_BIN_ID})
    _prop(main_bin, "xml_retain", "1")
    return mlt


def add_background(mlt: ET.Element, total_frames: int) -> None:
    """The mandatory full-length black track that content composites over."""
    last = total_frames - 1
    black = ET.SubElement(mlt, "producer", {
        "id": BLACK_PRODUCER_ID, "in": "0", "out": str(last),
    })
    _prop(black, "length", str(total_frames))
    _prop(black, "eof", "pause")
    _prop(black, "resource", "0")
    _prop(black, "mlt_service", "color")
    _prop(black, "mlt_image_format", "rgba")

    background = ET.SubElement(mlt, "playlist", {"id": BACKGROUND_PLAYLIST_ID})
    ET.SubElement(background, "entry", {
        "producer": BLACK_PRODUCER_ID, "in": "0", "out": str(last),
    })


def add_tractor(mlt: ET.Element, total_frames: int, content_playlist_ids: list[str],
                source_frame_rate_mode: str) -> ET.Element:
    """The tractor wiring the background and content tracks together.

    Each content track gets a `mix` (audio) and `qtblend` (video) transition
    against the background, which is what Shotcut writes for its own projects.
    """
    tractor = ET.SubElement(mlt, "tractor", {
        "id": TRACTOR_ID,
        "title": SHOTCUT_TITLE,
        "in": "0",
        "out": str(total_frames - 1),
    })
    _prop(tractor, "shotcut", "1")
    _prop(tractor, "shotcut:projectAudioChannels", "2")
    _prop(tractor, PROVENANCE_PROPERTY, source_frame_rate_mode)

    ET.SubElement(tractor, "track", {"producer": BACKGROUND_PLAYLIST_ID})
    for playlist_id in content_playlist_ids:
        ET.SubElement(tractor, "track", {"producer": playlist_id})

    transition_index = 0
    for track_index, _ in enumerate(content_playlist_ids, start=1):
        mix = ET.SubElement(tractor, "transition", {"id": f"transition{transition_index}"})
        _prop(mix, "a_track", "0")
        _prop(mix, "b_track", str(track_index))
        _prop(mix, "mlt_service", "mix")
        _prop(mix, "always_active", "1")
        _prop(mix, "sum", "1")
        transition_index += 1

        blend = ET.SubElement(tractor, "transition", {"id": f"transition{transition_index}"})
        _prop(blend, "a_track", "0")
        _prop(blend, "b_track", str(track_index))
        _prop(blend, "mlt_service", "qtblend")
        _prop(blend, "always_active", "1")
        transition_index += 1

    return tractor
