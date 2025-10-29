#!/usr/bin/env python3
"""
Generate app icon - white circle with red solid circle inside
Similar to the recording tray icon
"""
from PIL import Image, ImageDraw

# Create a high-resolution image (1024x1024 for best quality)
size = 1024
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Calculate dimensions
center = size // 2
outer_radius = int(size * 0.45)  # Outer circle radius
outer_width = int(size * 0.08)   # Width of outer circle stroke
inner_radius = int(size * 0.30)  # Inner solid circle radius

# Draw outer white circle (stroke only)
draw.ellipse(
    [(center - outer_radius, center - outer_radius),
     (center + outer_radius, center + outer_radius)],
    outline='white',
    width=outer_width,
    fill=None
)

# Draw inner red solid circle
draw.ellipse(
    [(center - inner_radius, center - inner_radius),
     (center + inner_radius, center + inner_radius)],
    fill='#FF3B30',  # iOS/macOS red color
    outline=None
)

# Save the icon
img.save('icon.png')
print("✓ Created icon.png (1024x1024)")
