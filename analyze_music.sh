#!/bin/bash
# 音乐分析工具 v2——渡渡和猫
# 用法: bash analyze_music.sh [mp3文件名]
# 环境变量: MUSIC_SERVER_PASS（服务器密码，不传则报错）

if [ -z "$MUSIC_SERVER_PASS" ]; then
    echo "❌ 请设置环境变量 MUSIC_SERVER_PASS"
    exit 1
fi

SERVER="${MUSIC_SERVER_HOST:-lighthouse@101.43.38.124}"
PASS="$MUSIC_SERVER_PASS"
CACHE="/home/lighthouse/eryu-main/server/data/music_cache"

# 找到MP3
if [ -n "$1" ]; then
    MP3="$CACHE/$1"
else
    MP3=$(sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$SERVER" "ls -t $CACHE/*.mp3 2>/dev/null | head -1")
fi

if [ -z "$MP3" ]; then echo "❌ 没找到mp3"; exit 1; fi

BNAME=$(basename "$MP3" .mp3)
echo "🎵 $BNAME"
echo ""

# 1. BPM / 调性 / 能量
echo "═══ BPM / 调性 / 能量 ═══"
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
    "bash -c 'source ~/music-env2/bin/activate && python3 ~/analyze_essentia.py $MP3'" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'BPM {d[\"bpm\"]}  |  {d[\"key\"]}  |  置信度 {d[\"strength\"]}')
print()
print('能量曲线:')
pts=d['energy']
for p in pts[::3]:
    bar='█'*int(p['e']/300)
    print(f'  {int(p[\"t\"])}s {bar}')
"

# 2. 色调
echo ""
echo "═══ 色调曲线 ═══"
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
    "python3 ~/analyze_chroma.py $MP3" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
notes=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
for seg in d[:20]:
    c=seg['chroma']
    top=sorted(range(12),key=lambda i:c[i],reverse=True)[:3]
    print(f\"  {int(seg['t'])}s  {' '.join(notes[i] for i in top)}\")
"

# 3. 歌词
echo ""
echo "═══ 歌词 ═══"
LRC="$CACHE/$BNAME.lrc"
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$SERVER" \
    "cat $LRC 2>/dev/null || echo '（无歌词文件）'" 2>/dev/null | head -30 | grep -v '^\[' | sed 's/^/  /'

echo ""
echo "✅ 完成"
