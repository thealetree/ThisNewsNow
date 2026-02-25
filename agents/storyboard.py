"""
Storyboard Agent — Converts scripts into visual assembly instructions.

For the Pi-viable version: no AI video generation. Uses:
- Looping anchor background video
- Pillow-generated chyron overlays
- Pre-downloaded royalty-free B-roll matched by keyword

Output: a shot list JSON consumed by video/assembler.py
"""


def generate_storyboard(script_data, config):
    """
    Convert a script into ffmpeg-ready visual instructions.

    Returns a shot list dict describing what to composite at each timestamp.
    """
    # TODO: Implement storyboard generation
    # For Phase A, the assembler handles this directly with a simple
    # bumper -> anchor_bg + chyrons -> bumper_outro structure.
    pass
