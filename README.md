# ForRocketWorkbench

[ForRocket](https://github.com/sus304/ForRocket) ロケット飛翔シミュレータのコントローラ。
単一飛行経路解析 / 落下エリア / モンテカルロシミュレーション / 感度解析の 4 モードをサポートする CLI ツールと PyQt5 GUI を提供する。

---

## 必要要件

| 項目 | バージョン |
|---|---|
| Python | 3.8 以上 |
| ForRocket バイナリ | v4.2.0 以上 |

### Python 依存パッケージ

```
numpy
scipy
pandas
matplotlib
tqdm
PyQt5        # GUI 使用時のみ
```

インストール例：

```bash
pip install numpy scipy pandas matplotlib tqdm
pip install PyQt5  # GUI 使用時
```

---

## セットアップ

1. リポジトリをクローンまたは展開する
2. ForRocket バイナリをリポジトリルートに配置する

```
ForRocketWorkbench/
└── ForRocket.exe   ← ここに配置（Linux なら ForRocket）
```

3. プロジェクトディレクトリを作成して設定ファイルを配置する（後述の推奨構成参照）

---

## 使い方

### 共通の制約

`runner.py` は **設定ファイルが置かれているディレクトリを CWD** にして実行する必要がある。
作業ディレクトリ（`work_trajectory/` 等）も CWD に生成される。

```bash
cd ~/ForRocketWorkbench/projects/example/
python ../../runner.py -s config_solver.json
```

### 1. Trajectory 計算

単一条件の飛翔シミュレーション。

```bash
python runner.py -s config_solver.json
```

出力：`work_trajectory/result_<ModelID>/` にサマリ・グラフ・KML。

### 2. 落下エリア計算

風向×風速の格子ケースを並列実行し、落下点エンベロープを KML で出力する。

```bash
python runner.py -s config_solver.json -a config_area.json [-X]
python post.py -a work_area/        # 後処理のみ再実行する場合
```

`-X` を付けると CPU スレッドを最大利用して並列化。

出力：`work_area/area.kml`（パラシュート有）、`work_area/area_ballistic.kml`（弾道）。

### 3. MonteCarlo シミュレーション

誤差パラメータを確率分布でサンプリングして大量ケースを実行し、落下点 3σ 楕円を推定する。

```bash
python runner.py -s config_solver.json -m config_montecarlo.json [-X]
python post.py -m work_montecarlo/  # 後処理のみ再実行する場合
```

出力：`work_montecarlo/montecarlo_envelope.kml`、`result_table.csv`、`montecarlo_3sigma_summary.txt`。

### 4. 感度解析

各パラメータを独立に変化させ、頂点高度への感度係数とトルネードチャートを出力する。
後処理は `runner.py` が自動実行するため `post.py` は不要。

```bash
python runner.py -s config_solver.json -e config_sensitivity.json [-X]
```

出力：`work_sensitivity/sensitivity_results.csv`、`sensitivity_tornado.png`。

### GUI

```bash
python ForRocketWorkbench.py
```

Trajectory / Area / MonteCarlo の 3 モードをサポート。感度解析は CLI のみ対応。

---

## 設定ファイルリファレンス

### `config_solver.json`

全モードで共通のベース設定。

```json
{
    "Model ID": "sample",
    "Launch DateTime": "2026/01/01 6:00:00.0",
    "Launch Condition": {
        "Latitude [deg]": 31.25,
        "Longitude [deg]": 131.08,
        "Height for WGS84 [m]": 100.0,
        "Azimuth [deg]": 90.0,
        "Elevation [deg]": 85.0,
        "North Velocity [m/s]": 0.0,
        "East Velocity [m/s]": 0.0,
        "Down Velocity [m/s]": 0.0,
        "Yaw Angular Velocity [deg/s]": 0.0,
        "Pitch Angular Velocity [deg/s]": 0.0,
        "Roll Angular Velocity [deg/s]": 0.0,
        "Moving equivalent wind mode": true
    },
    "Wind Condition": {
        "Enable Wind": true,
        "Wind File Path": "wind.csv"
    },
    "Number of Stage": 1,
    "Stage1 Config File List": "param_list_stage1.json"
}
```

| キー | 説明 |
|---|---|
| `Model ID` | 出力ファイル名のプレフィックス |
| `Moving equivalent wind mode` | `true` の場合、射出高度の風速を初期速度に加算（大気静止系等価） |
| `Wind File Path` | 風プロファイル CSV（`alt[m],u[m/s],v[m/s]` 形式） |

### 風プロファイル CSV (`wind.csv`)

```
alt[m],u[m/s],v[m/s]
0,3.0,-1.0
500,4.5,-1.5
...
```

### `config_area.json`

落下エリア計算の風格子設定。

```json
{
    "Law Wind": {
        "Wind Characteristic Coefficient": 0.143,
        "Reference Height [m]": 10.0,
        "Reference Wind Speed Lower Limit [m/s]": 2.0,
        "Reference Wind Speed Upper Limit [m/s]": 10.0,
        "Reference Wind Speed Step [m/s]": 2.0,
        "Wind Direction Lower Limit [deg]": 0.0,
        "Wind Direction Upper Limit [deg]": 350.0,
        "Wind Direction Step [deg]": 10.0
    }
}
```

| キー | 説明 |
|---|---|
| `Wind Characteristic Coefficient` | べき乗則の指数（冪指数）。市街地 0.3、平野 0.143 等 |
| `Reference Height [m]` | 風速の参照高度 |
| 風速・風向の各 Limit / Step | 格子の範囲と刻み幅 |

### `config_montecarlo.json`

```json
{
    "MonteCarlo Case Count": 1000,
    "Error Parameters": {
        "Wind": {
            "Enable": true,
            "Wind Files Zip Path": "winds.zip"
        },
        "Launcher Elevation": {
            "Enable": true,
            "Error Unit": "deg",
            "Error 3sigma Low": 5.0,
            "Error 3sigma High": 5.0
        },
        "Thrust": {
            "Enable": true,
            "Error Unit": "%",
            "Error 3sigma Low": 5.0,
            "Error 3sigma High": 5.0
        }
    }
}
```

各誤差パラメータ共通キー：

| キー | 説明 |
|---|---|
| `Enable` | `true` でこのパラメータの誤差を有効化 |
| `Error Unit` | `"%"` で名目値に対する割合、それ以外の文字列で絶対値（単位はドキュメント用） |
| `Error 3sigma Low` | 名目値より小さい側の 3σ 値 |
| `Error 3sigma High` | 名目値より大きい側の 3σ 値 |

対応パラメータ：`Wind`, `Launcher Azimuth`, `Launcher Elevation`, `Propellant Mass`, `Mass Inert`, `Thrust`, `CA`, `XCG`, `MOI`, `CNa`, `XCP`, `Cld`, `Clp`, `Cmq`, `Cnr`, `Fin Cant Angle`, `Engine Miss-Alignment Y`, `Engine Miss-Alignment Z`, `Primary Parachute Drag`, `Primary Parachute Open Time`, `Secondary Parachute Drag`, `Secondary Parachute Open Time`

### `config_sensitivity.json`

```json
{
    "Sensitivity Calculation": {
        "Method": "two_point"
    },
    "Sensitivity Parameters": [
        {
            "Name": "Thrust",
            "Variation Unit": "%",
            "Variations": [-10, -5, 5, 10],
            "Reference Variations": [-10, 10]
        },
        {
            "Name": "Launcher Elevation",
            "Variation Unit": "deg",
            "Variations": [-5, -2, 2, 5]
        }
    ]
}
```

| キー | 説明 |
|---|---|
| `Method` | `"two_point"`（指定 2 点の差分）または `"linear_fit"`（最小二乗線形回帰） |
| `Name` | 解析対象パラメータ名（MonteCarlo の対応パラメータと同一）。ただし `Wind` は不可、`Thrust` と `CA` はファイルモード時も倍率として処理 |
| `Variation Unit` | `%` または物理単位文字列 |
| `Variations` | 名目値からの変化量のリスト |
| `Reference Variations` | `two_point` 時の差分計算に使う `[lo, hi]`（省略時は Variations の最小/最大） |

---


