# fugu-xday-forecast

萬栄丸のトラフグ釣果を `maneimaru.jp` から取得し、気温・水温・月齢を組み合わせて当年の `2月1日から4月30日まで` の `X-Day` 確率と予測匹数を日別に可視化する静的アプリです。

## 使い方

```bash
git clone https://github.com/wak-shogo/fugu-xday-forecast.git
cd fugu-xday-forecast
python3 scripts/generate_data.py
python3 -m http.server 8000
```

`http://localhost:8000` を開くと表示できます。

## 再生成

現在日付基準で今年分を再生成:

```bash
python3 scripts/generate_data.py
```

年を固定して再生成:

```bash
python3 scripts/generate_data.py --year 2026 --today 2026-03-25
```

## データ元

- 萬栄丸: `https://www.maneimaru.jp/`
- Open-Meteo archive / forecast / marine APIs

## モデル

ローカルの生成スクリプトで、`気温 / 水温 / 月齢` とその交互作用項を使った回帰モデルを3本学習します。月齢は `sin / cos` の周期特徴量へ変換しているため、`29日台` と `0日台` の境目でも不自然な段差が出にくい形です。

- `X-Day` 確率
- 予測最小匹数
- 予測最大匹数

生成後は係数だけを `data/predictions.json` に保存し、ブラウザ側ではその重みを使ってスライダー操作に即時反応するシミュレーターを動かします。
