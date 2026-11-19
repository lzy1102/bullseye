#!/bin/sh
# 等 60 分钟线补齐 800 只后自动跑入场择时。
cd /opt/bullseye || exit 1
i=0
while [ $i -lt 120 ]; do
    i=$((i + 1))
    n=$(ls user_data/data_60m 2>/dev/null | wc -l)
    [ "$n" -ge 790 ] && break
    sleep 300
done
echo "[$(date '+%F %T')] 60m files=$(ls user_data/data_60m | wc -l), running entry timing"
docker run --rm --entrypoint python3 \
    -v /opt/bullseye/user_data:/app/user_data \
    -v /opt/bullseye/scripts:/app/scripts:ro bullseye:latest \
    scripts/research/entry_timing.py --data user_data/data_fund/kline \
    --d60 user_data/data_60m --universe '' --start 2020-01-01 \
    >> /var/log/entry_timing.log 2>&1
echo "[$(date '+%F %T')] done" >> /var/log/entry_timing.log
