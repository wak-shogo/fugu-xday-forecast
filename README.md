# fugu-xday-forecast

萬栄丸のトラフグ釣果を `maneimaru.jp` から取得し、気温・水温・月齢を組み合わせて当年の `X-Day` 確率を日別に棒グラフ化する静的アプリです。

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

過去の `X-Day` と非 `X-Day` を、気温・水温・月齢の近さで重み付けする非パラメトリックな確率モデルです。さらに、トラフグ投稿が集中していた時期の季節性を別スコアとして掛け合わせています。
