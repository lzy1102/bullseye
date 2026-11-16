#!/bin/sh
# 等待数据源恢复后自动补齐 HS300+ZZ500（800 只）的 K 线与财务。
# 每轮有超时保护：baostock 会无响应挂死，必须强制结束再重试。
cd /opt/bullseye || exit 1
for i in $(seq 1 40); do
    n=$(ls user_data/data_fund/kline 2>/dev/null | wc -l)
    f=$(ls user_data/data_fund/fin 2>/dev/null | wc -l)
    echo "[$(date '+%F %T')] round $i kline=$n fin=$f"
    [ "$n" -ge 800 ] && [ "$f" -ge 800 ] && { echo "all done"; break; }
    timeout 1200 docker run --rm --name fetch_idx \
        --entrypoint python3 \
        -v /opt/bullseye/user_data:/app/user_data \
        -v /opt/bullseye/scripts:/app/scripts:ro \
        bullseye:latest scripts/research/fetch_fundamentals_fast.py \
        --index both --out user_data/data_fund --workers 6 >> /tmp/fetch_idx.log 2>&1
    docker rm -f fetch_idx >/dev/null 2>&1
    sleep 600
done
echo "[$(date '+%F %T')] loop finished"
