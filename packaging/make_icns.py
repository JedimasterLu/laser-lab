"""Create ``packaging/laserscan.icns`` from the Windows icon (needs Pillow).

macOS draws a Dock icon edge to edge, so a full-bleed icon looks larger than other apps':
the artwork is scaled into the standard 824/1024 body on a transparent square.
"""

from pathlib import Path

from PIL import Image

here = Path(__file__).parent
SIZE = 1024
art = Image.open(here / "laserscan.ico").convert("RGBA").resize((SIZE * 824 // 1024,) * 2, Image.LANCZOS)
canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
canvas.paste(art, ((SIZE - art.width) // 2,) * 2, art)
canvas.save(here / "laserscan.icns")
