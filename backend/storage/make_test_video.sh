#!/bin/bash
# Generates a short spoken-word test video for validating the pipeline.
set -e
OUT_DIR=/app/backend/storage
TXT="$OUT_DIR/script.txt"
WAV="$OUT_DIR/speech.wav"
VID="$OUT_DIR/test_video.mp4"

cat > "$TXT" << 'EOF'
Here is the single biggest mistake people make when they start investing. They wait for the perfect moment. The truth is, the perfect moment never comes, and waiting costs you more than being wrong.
Let me tell you a quick story. A friend of mine saved money for ten years but never invested a single dollar. He lost more to inflation than he ever would have lost in the market.
Now here is the surprising part. Studies show that time in the market beats timing the market almost every single time. Just staying invested is the real secret.
So my strong opinion is this. Stop trying to be a genius. Be consistent instead. Consistency is boring, but boring makes you rich.
EOF

espeak-ng -f "$TXT" -s 165 -w "$WAV"
ffmpeg -y -f lavfi -i color=c=0x18181A:s=1280x720:r=25 -i "$WAV" \
  -shortest -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac "$VID"
echo "created $VID"
ffprobe -v quiet -show_format "$VID" | grep duration
