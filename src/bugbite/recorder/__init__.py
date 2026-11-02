"""Recorder: structured, readable recordings of every run (README FR10)."""

from .observer import RunRecorder, outcome_of
from .reader import LoadedRecording, ModelCallRecord, load_recording
from .start import Recording, RecordingInfo, bugbite_commit_info, default_environment, start_recording
from .writer import DEFAULT_MAX_BYTES, EVENTS, FORMAT, FORMAT_VERSION, MANIFEST, RecordingError, RunWriter

__all__ = [
    "RunWriter", "RunRecorder", "Recording", "RecordingInfo", "RecordingError", "LoadedRecording", "ModelCallRecord",
    "start_recording", "load_recording", "bugbite_commit_info", "default_environment", "outcome_of",
    "FORMAT", "FORMAT_VERSION", "MANIFEST", "EVENTS", "DEFAULT_MAX_BYTES",
]
