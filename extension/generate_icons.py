#!/usr/bin/env python3
"""
Generate PNG icons for the AI Assistant Chrome Extension.

Run this script to create the required icon files:
    python generate_icons.py

Requires PIL/Pillow:
    pip install Pillow
"""

import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow not installed. Installing...")
    os.system("pip install Pillow")
    from PIL import Image, ImageDraw


def create_icon(size: int, output_path: str):
    """Create a simple gradient icon with a lightning bolt."""
    # Create image with transparency
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw gradient circle background
    center = size // 2
    radius = int(size * 0.45)
    
    for r in range(radius, 0, -1):
        # Gradient from cyan to darker cyan
        ratio = r / radius
        color = (
            int(0 + (0 * ratio)),           # R
            int(212 - (60 * (1 - ratio))),  # G  
            int(255 - (50 * (1 - ratio))),  # B
            255                              # A
        )
        draw.ellipse(
            [center - r, center - r, center + r, center + r],
            fill=color
        )
    
    # Draw lightning bolt
    bolt_color = (255, 255, 255, 255)
    
    # Scale factor
    s = size / 32
    
    # Upper triangle of bolt
    upper_points = [
        (16 * s, 8 * s),   # top
        (20 * s, 16 * s),  # right
        (16 * s, 14 * s),  # middle
        (12 * s, 16 * s),  # left
    ]
    draw.polygon(upper_points, fill=bolt_color)
    
    # Lower triangle of bolt
    lower_points = [
        (16 * s, 24 * s),  # bottom
        (12 * s, 16 * s),  # left
        (16 * s, 18 * s),  # middle
        (20 * s, 16 * s),  # right
    ]
    draw.polygon(lower_points, fill=bolt_color)
    
    # Save
    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")


def main():
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    icons_dir = script_dir / "assets" / "icons"
    
    # Create icons directory if it doesn't exist
    icons_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate icons at required sizes
    sizes = [16, 32, 48, 128]
    
    for size in sizes:
        output_path = icons_dir / f"icon{size}.png"
        create_icon(size, str(output_path))
    
    print("\n✅ All icons generated successfully!")
    print(f"   Location: {icons_dir}")


if __name__ == "__main__":
    main()

