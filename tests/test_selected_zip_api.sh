#!/usr/bin/env bash
# 多选打包下载 · 后端边界测试（路径穿越/空选/目录打包/去重）
# 用法：./tests/test_selected_zip_api.sh [base_url]
set -u
BASE="${1:-http://127.0.0.1:8099}"
pass=0; fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✔ $1: $2"; pass=$((pass+1)); else echo "  ✘ $1: $2 (期望 $3)"; fail=$((fail+1)); fi; }

echo "【路径穿越防护】"
for bad in "../../etc/passwd" "/etc/passwd" "docs/../../../etc/hostname"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST --data-urlencode "paths=$bad" --max-time 15 "$BASE/api/download-selected")
  chk "拒绝 $bad" "$code" "400"
done

echo "【空选择】"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST --max-time 15 "$BASE/api/download-selected")
chk "空提交" "$code" "400"

echo "【目录打包】"
curl -s -X POST --data-urlencode "paths=论文插图" --max-time 60 "$BASE/api/download-selected" -o /tmp/_t_dir.zip
n=$(python3 -c "import zipfile;print(len(zipfile.ZipFile('/tmp/_t_dir.zip').namelist()))" 2>/dev/null || echo 0)
chk "目录条目数>0" "$([ "$n" -gt 0 ] && echo yes || echo no)" "yes"

echo "【文件+目录混合去重】"
curl -s -X POST --data-urlencode "paths=论文/README.md" --data-urlencode "paths=论文" --data-urlencode "paths=论文/draft/README.md" \
  --max-time 120 "$BASE/api/download-selected" -o /tmp/_t_mix.zip
dup=$(python3 -c "
import zipfile;n=zipfile.ZipFile('/tmp/_t_mix.zip').namelist()
print(sum(1 for x in set(n) if n.count(x)>1))" 2>/dev/null || echo -1)
chk "无重复条目" "$dup" "0"
rm -f /tmp/_t_dir.zip /tmp/_t_mix.zip

echo
echo "结果: 通过 $pass / 失败 $fail"
[ "$fail" -eq 0 ]
