#!/bin/sh
# 等全市场数据补齐后自动跑：点时池 -> 补财务 -> 点时多因子回测。
# 日志：/var/log/pit_pipeline.log
cd /opt/bullseye || exit 1
DOCKER="docker run --rm --entrypoint python3 -v /opt/bullseye/user_data:/app/user_data -v /opt/bullseye/scripts:/app/scripts:ro bullseye:latest"
TARGET=${TARGET:-5150}

i=0
while [ $i -lt 500 ]; do
    i=$((i + 1))
    n=$(ls user_data/data_all/*-1d.parquet 2>/dev/null | wc -l)
    running=$(docker ps --format '{{.Names}}' | grep -c fetch_daily)
    echo "[$(date '+%F %T')] kline=$n running=$running"
    if [ "$n" -ge "$TARGET" ] && [ "$running" -eq 0 ]; then
        echo "[$(date '+%F %T')] data ready, starting pipeline"
        break
    fi
    sleep 600
done

if [ "$(ls user_data/data_all/*-1d.parquet 2>/dev/null | wc -l)" -lt "$TARGET" ]; then
    echo "[$(date '+%F %T')] gave up waiting"; exit 1
fi

$DOCKER scripts/research/build_pit_universe.py \
    --data user_data/data_all --top 300 \
    --out user_data/data_all/pit_top300.parquet >> /var/log/pit_pipeline.log 2>&1

cd /app 2>/dev/null
docker run --rm --entrypoint python3 -w /app/scripts/research \
    -v /opt/bullseye/user_data:/app/user_data \
    -v /opt/bullseye/scripts:/app/scripts:ro bullseye:latest \
    fetch_fin_union.py --pit user_data/data_all/pit_top300.parquet \
    --fin-dir user_data/data_all_fin --workers 8 >> /var/log/pit_pipeline.log 2>&1

for W in "2016-01-01 2020-12-31" "2021-01-01 2026-10-10" "2016-01-01 2026-10-10"; do
    set -- $W
    echo "=== $1 .. $2 ===" >> /var/log/pit_pipeline.log
    docker run --rm --entrypoint python3 \
        -v /opt/bullseye/user_data:/app/user_data \
        -v /opt/bullseye/scripts:/app/scripts:ro bullseye:latest \
        scripts/research/multifactor.py --data user_data/data_all \
        --kline-dir user_data/data_all --fin-dir user_data/data_all_fin \
        --universe user_data/data_all/pit_top300.parquet \
        --start $1 --end $2 >> /var/log/pit_pipeline.log 2>&1
done
echo "[$(date '+%F %T')] pipeline finished" >> /var/log/pit_pipeline.log
