import os
import struct
import zlib
import math

def create_png(width, height, get_pixel):
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # filter type 0 (None)
        for x in range(width):
            r, g, b, a = get_pixel(x, y, width, height)
            raw_data.extend([r, g, b, a])
    
    def chunk(tag, data):
        c = tag + data
        crc = zlib.crc32(c) & 0xffffffff
        return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)
    
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(bytes(raw_data), 9))
    iend = chunk(b'IEND', b'')
    return header + ihdr + idat + iend

def shortbot_icon_pixel(x, y, w, h):
    # Normalized coords [0, 1]
    nx = x / (w - 1) if w > 1 else 0.5
    ny = y / (h - 1) if h > 1 else 0.5
    
    # Rounded rectangle mask
    radius = 0.22
    dx = max(0.0, abs(nx - 0.5) - (0.5 - radius))
    dy = max(0.0, abs(ny - 0.5) - (0.5 - radius))
    dist = math.hypot(dx, dy)
    if dist > radius:
        return (0, 0, 0, 0)
    
    # YouTube Red / Crimson gradient
    # Top-left to bottom-right
    t = (nx + ny) / 2.0
    r_bg = int(255 * (1 - t * 0.2))
    g_bg = int(24 + 10 * t)
    b_bg = int(60 + 20 * t)

    # Center play button / triangle
    # Coordinates of play triangle pointing right
    # Centered around (0.52, 0.5)
    tx = (nx - 0.36) / 0.32
    ty = (ny - 0.5) / 0.24
    
    # Triangle condition: tx >= 0, ty <= tx/2, ty >= -tx/2
    in_triangle = (tx >= 0) and (tx <= 1) and (abs(ty) <= (1 - tx))
    
    if in_triangle:
        return (255, 255, 255, 255)
    
    # Subtle border highlight
    border_dist = radius - dist
    if border_dist < 0.04 and border_dist >= 0:
        return (min(255, r_bg + 40), min(255, g_bg + 40), min(255, b_bg + 40), 255)

    return (r_bg, g_bg, b_bg, 255)

def main():
    icons_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "icons")
    os.makedirs(icons_dir, exist_ok=True)
    
    for size in (16, 48, 128):
        data = create_png(size, size, shortbot_icon_pixel)
        filepath = os.path.join(icons_dir, f"icon-{size}.png")
        with open(filepath, "wb") as f:
            f.write(data)
        print(f"Generated {filepath} ({size}x{size})")

if __name__ == "__main__":
    main()
