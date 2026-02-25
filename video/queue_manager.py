"""
Queue Manager — Manages the stream buffer of pre-rendered clips. (Phase C)

Maintains playlist.txt for ffmpeg concat, ensures minimum buffer
is always available, handles clip rotation and disk cleanup.
"""

# TODO: Implement in Phase C
# - Maintain playlist.txt (ffmpeg concat format)
# - Keep at least buffer_minimum_seconds of clips rendered ahead
# - Emergency bumper loop if queue runs low
# - Auto-cleanup of streamed clips
