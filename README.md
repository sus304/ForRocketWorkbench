# ForRocketWorkbench

[ForRocket](https://github.com/sus304/ForRocket) ロケット飛翔シミュレータの Web フロントエンド。  
ブラウザから設定編集・計算実行・結果確認をワンストップで行える。

単一飛行経路 / 落下エリア / モンテカルロ / 感度解析 の 4 モードをサポート。

---

## 必要要件

| 項目 | バージョン |
|---|---|
| Python | 3.10 以上 |
| ForRocket バイナリ | v4.2.0 以上 |

### Python 依存パッケージ

```
nicegui
fastapi
sqlalchemy
numpy
scipy
pandas
matplotlib
tqdm
```

インストール例：

```bash
pip install nicegui fastapi sqlalchemy numpy scipy pandas matplotlib tqdm
```

---

## セットアップ

1. リポジトリをクローンまたは展開する
2. ForRocket バイナリをリポジトリルートに配置する

```
ForRocketWorkbench/
└── ForRocket.exe   ← ここに配置（Linux なら ForRocket）
```

3. アプリを起動する

```bash
python main.py
```

ブラウザで `http://localhost:8080` を開く。

---

## 画面構成

### Dashboard (`/`)

プロジェクト一覧と計算履歴を表示する。  
プロジェクト名をクリックすると Calculate 画面に遷移し、設定編集・計算実行ができる。

### Calculate (`/calculate`)

**設定編集**と**計算実行**を一体化した画面。

- **左ペイン（Config Editor）**  
  ファイルセレクタで編集対象を切り替え。  
  各ファイルはフォームタブ（GUI 入力）と JSON タブを切り替えて編集できる。  
  Save ボタンでファイルに書き込む。

- **右ペイン（Run Controls、スティッキー）**  
  モード選択・スレッド設定・ファイル状態表示・実行/キャンセルボタン・進捗表示。  
  計算完了後は「View Results」ボタンと 3 秒後の自動遷移（「Stay here」でキャンセル可）。

URL パラメータ：
- `?project=<name>` — 指定プロジェクトを初期選択
- `?new=1` — 起動時に新規プロジェクトダイアログを開く

### Result (`/result/<calc_id>`)

計算結果の可視化画面。モードに応じて表示内容が変わる。

| モード | 表示内容 |
|---|---|
| Trajectory | 飛翔サマリ（Launcher Clear / Max Q / Max Speed / Apogee / Impact）・時系列グラフ（高度・速度・マッハ・動圧・G-Load・AoA・ダウンレンジ・弾道）・Leaflet 落下点マップ |
| Area | 落下エリア KML ダウンロード |
| MonteCarlo | 統計サマリ（mean / σ / ±3σ）・4パラメータのヒストグラム・NE 散布図（1σ/2σ/3σ 楕円）・Leaflet 落下点マップ（分散楕円付き） |
| Sensitivity | トルネードチャート・感度テーブル・線形性チェック散布図（折りたたみ可） |

### Tools

- **Barrowman CP 計算器** (`/tools/barrowman`)  
  ノーズ・ボディ・フィンのジオメトリから CP 位置を Barrowman 法で計算。

- **Mass & Inertia 計算器** (`/tools/mass`)  
  コンポーネントごとの質量・CG・慣性モーメントを入力し、合計 CG・Iyy・Ixx を計算。CG 位置ダイアグラム付き。

- **Hybrid Engine 計算器** (`/tools/engine`)  
  ハイブリッドエンジンの推力・比推力・酸化剤流量を計算。

---

## 設定ファイルリファレンス

### `config_solver.json`

全モード共通のベース設定。

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
    }
}
```

| キー | 説明 |
|---|---|
| `Model ID` | 出力ファイル名のプレフィックス |
| `Moving equivalent wind mode` | `true` の場合、射出高度の風速を初期速度に加算（大気静止系等価） |
| `Wind File Path` | 風プロファイル CSV（`alt[m],u[m/s],v[m/s]` 形式） |

---

### `param_list_stage1.json`

ステージ 1 の各設定ファイルへのパスリスト。

```json
{
    "Rocket Configuration File Path": "param_rocket.json",
    "Engine Configuration File Path": "param_engine.json",
    "Sequence of Event File Path":    "sequence_of_event.json"
}
```

---

### `param_rocket.json`

ロケット本体パラメータ。主なキー：

| キー | 説明 |
|---|---|
| `Diameter [mm]` | 機体直径 |
| `Length [mm]` | 全長 |
| `Mass.Inert [kg]` | 乾燥質量 |
| `Mass.Propellant [kg]` | 推進剤質量 |
| `Enable X-C.G. File` / `Constant X-C.G.` | CG ファイル or 定数 |
| `Enable M.I. File` / `Constant M.I.` | 慣性モーメント ファイル or 定数 |
| `Enable X-C.P. File` / `Constant X-C.P.` | CP ファイル or 定数 |
| `Enable CA File` / `Constant CA` | 軸力係数 CA ファイル or 定数（バーンアウト後も別設定可） |
| `Enable CNa File` / `Constant CNa` | 法線力傾斜 CNα ファイル or 定数 |
| `Fin Cant Angle [deg]` | フィンキャント角 |
| `Enable Cld File` / `Constant Cld` | ロール力係数 ファイル or 定数 |
| `Enable Clp/Cmq/Cnr File` / 各定数 | 各ダンピング係数 |
| `Enable Gas Jet` | ガスジェット（スピン制御）の有無 |
| `Enable Program Attitude` | プログラム姿勢制御の有無 |

---

### `param_engine.json`

エンジンパラメータ。

| キー | 説明 |
|---|---|
| `Nozzle Exit Diameter [mm]` | ノズル出口径 |
| `Enable Thrust File` | 推力カーブ CSV を使用するか |
| `Constant Thrust.Thrust at vacuum [N]` | 真空推力（定数モード） |
| `Constant Thrust.Propellant Mass Flow Rate [kg/s]` | 推進剤質量流量 |
| `Constant Thrust.Burn Duration [sec]` | 燃焼時間 |
| `Enable Engine Miss Alignment` | エンジン軸ずれの有無 |
| `Engine Miss-Alignment.y-Axis Angle [deg]` | y 軸方向ずれ角 |
| `Engine Miss-Alignment.z-Axis Angle [deg]` | z 軸方向ずれ角 |

---

### `sequence_of_event.json`

フライトシーケンス設定。

| キー | 説明 |
|---|---|
| `Flight Start Time [s]` | 飛翔開始時刻 |
| `Engine Ignittion Time [s]` | エンジン点火時刻 |
| `Flight End Time [s]` | シミュレーション終了時刻 |
| `Time Step [s]` | 積分ステップ |
| `Enable Auto Terminate SubOrbital Flight` | 着地検出で自動終了 |
| `Enable Rail-Launcher Launch` / `Rail Launcher.Length [m]` | ランチレール使用 |
| `Enable Engine Cutoff` / `Cutoff.Cutoff Time [s]` | 強制カットオフ |
| `Enable Stage Separation` / `Upper Stage` | 段間分離 |
| `Enable Despin Control` / `Despin.Time [s]` | デスピン |
| `Enable Fairing Jettson` / `Fairing` | フェアリング分離 |
| `Enable Parachute Open` / `Parachute` | メインパラシュート |
| `Enable Secondary Parachute Open` / `Secondary Parachute` | セカンダリパラシュート |

---

### `config_area.json`

落下エリア計算の風格子設定（べき乗則風速モデル）。

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
| `Wind Characteristic Coefficient` | べき乗則指数。市街地 ≈ 0.30、平野 ≈ 0.143 |
| `Reference Height [m]` | 参照風速の計測高度 |
| 風速・風向の Limit / Step | 格子の範囲と刻み幅 |

ケース数 = 風速ステップ数 × 風向ステップ数。Calculate 画面のフォームでリアルタイム表示される。

---

### `config_montecarlo.json`

モンテカルロ誤差パラメータ設定。

```json
{
    "MonteCarlo Case Count": 300,
    "Error Parameters": {
        "Wind": {
            "Enable": false,
            "Wind Files Zip Path": "winds.zip"
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

各誤差パラメータの共通キー：

| キー | 説明 |
|---|---|
| `Enable` | このパラメータの誤差を有効化 |
| `Error Unit` | `"%"` で名目値に対する割合、それ以外で絶対値（単位はドキュメント用） |
| `Error 3sigma Low` | 名目値より小さい側の 3σ 値 |
| `Error 3sigma High` | 名目値より大きい側の 3σ 値 |

`Wind` のみ `Wind Files Zip Path` を使用（σ 値なし）。

対応する 22 パラメータ：

| カテゴリ | パラメータ名 |
|---|---|
| ランチャ | `Launcher Azimuth`, `Launcher Elevation` |
| 空力 | `CA`, `CNa`, `XCP`, `Cld`, `Clp`, `Cmq`, `Cnr`, `Fin Cant Angle` |
| 質量 | `Propellant Mass`, `Mass Inert`, `MOI`, `XCG` |
| エンジン | `Thrust`, `Engine Miss-Alignment Y`, `Engine Miss-Alignment Z` |
| パラシュート | `Primary Parachute Drag`, `Primary Parachute Open Time`, `Secondary Parachute Drag`, `Secondary Parachute Open Time` |
| 風 | `Wind` |

---

### `config_sensitivity.json`

感度解析設定。各パラメータを独立に変化させ、頂点高度への感度係数を計算する。

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
        }
    ]
}
```

| キー | 説明 |
|---|---|
| `Method` | `"two_point"`（指定 2 点の差分）または `"linear_fit"`（最小二乗線形回帰） |
| `Name` | 解析対象パラメータ名（`config_montecarlo.json` の対応パラメータと同一、`Wind` を除く） |
| `Variation Unit` | `%` または物理単位文字列 |
| `Variations` | 名目値からの変化量リスト（正負両側を推奨） |
| `Reference Variations` | `two_point` 時の差分計算に使う `[lo, hi]`（省略時は Variations の最小/最大） |

結果画面には以下が表示される：
- **トルネードチャート** — 各パラメータの頂点高度影響度を降順表示
- **感度テーブル** — 感度係数 [m/unit] と [m/%]、各高度値
- **線形性チェック（折りたたみ）** — 全解析点の散布図と線形傾きの比較。Reference Variations（オレンジ◆）、通常点（青●）、ノミナル（緑▲）で色分け。X・Y 軸はノミナル値を中心に対称表示。

---

## プロジェクト構成

```
ForRocketWorkbench/
├── main.py                     # エントリポイント（NiceGUI アプリ起動）
├── runner.py                   # 計算実行ラッパー
├── post.py                     # 後処理ラッパー
├── projects/                   # プロジェクトディレクトリ
│   └── <project_name>/
│       ├── config_solver.json
│       ├── param_list_stage1.json
│       ├── param_rocket.json
│       ├── param_engine.json
│       ├── sequence_of_event.json
│       ├── config_area.json        # Area モード
│       ├── config_montecarlo.json  # MonteCarlo モード
│       └── config_sensitivity.json # Sensitivity モード
├── web/
│   ├── pages/
│   │   ├── shared.py           # ヘッダ・バッジ共通部品
│   │   ├── dashboard.py        # Dashboard ページ
│   │   ├── calculate.py        # Calculate ページ（設定編集 + 計算実行）
│   │   ├── result.py           # Result ページ
│   │   ├── tools_barrowman.py  # Barrowman CP 計算器
│   │   ├── tools_mass.py       # Mass & Inertia 計算器
│   │   └── tools_engine.py     # Hybrid Engine 計算器
│   ├── services/
│   │   ├── calc_service.py     # 計算ジョブ管理（スレッド・DB）
│   │   └── project_service.py  # プロジェクトディレクトリ・JSON IO
│   ├── db/
│   │   ├── database.py         # SQLAlchemy セッション管理
│   │   └── models.py           # Project / Calculation モデル
│   └── tools/
│       ├── barrowman.py        # Barrowman 計算ロジック
│       └── mass_budget.py      # 質量・慣性計算ロジック
├── runner_tool/                # 各モードのランナー
├── post_tool/                  # 各モードの後処理
└── tests/                      # pytest テストスイート
    ├── conftest.py
    ├── test_calc_service.py
    ├── test_db_models.py
    ├── test_form_builders.py   # フォームビルダー入出力テスト
    └── test_project_service.py
```

---

## テスト

```bash
python -m pytest tests/ -v
```

テストはインメモリ SQLite を使用するため外部リソース不要。  
`test_form_builders.py` は NiceGUI の UI 要素をスタブに差し替え、全フォームビルダーの入出力ラウンドトリップを検証する。

---

## CLI から直接実行する場合

Web UI を使わず CLI で実行する場合は以下の通り。

```bash
cd projects/<project_name>

# Trajectory
python ../../runner.py -s config_solver.json
python ../../post.py -c work_trajectory/<work_dir>

# Area
python ../../runner.py -s config_solver.json -a config_area.json [-X]
python ../../post.py -a work_area/<work_dir>

# MonteCarlo
python ../../runner.py -s config_solver.json -m config_montecarlo.json [-X]
python ../../post.py -m work_montecarlo/<work_dir>

# Sensitivity（後処理は runner が自動実行）
python ../../runner.py -s config_solver.json -e config_sensitivity.json [-X]
```

`-X` を付けると CPU スレッドを最大利用して並列化（Area / MonteCarlo / Sensitivity）。
