# ForRocketWorkbench

[ForRocket](https://github.com/sus304/ForRocket) ロケット飛翔シミュレータを駆動する計算サービス + Web フロントエンド。
ブラウザからプロジェクト（設定一式）の編集・計算の投入・結果確認までを行える。

単一飛行経路 / 落下エリア / モンテカルロ / 感度解析 の 4 モードをサポート。

---

## 構成

2つのプロセスに分かれている。

| プロセス | 起動コマンド | 役割 |
|---|---|---|
| 計算サービス | `python -m service.serve` | ジョブのキュー・実行・結果保持。HTTP API を提供する |
| Web UI | `python app_server.py` | ブラウザ向けフロント。計算サービスの API を叩くだけで、計算状態を持たない |

計算はサービスのワーカが所有する子プロセスとして走るため、**ブラウザを閉じても UI を再起動してもジョブは走り続ける**。
ワーカは単一 FIFO で、ジョブは一度に1つずつ実行される（ソルバはメモリ帯域バウンドで、ジョブを並列に走らせても
スループットは上がらないため）。

同じ API を CLI クライアント `wb`（`cli/wb.py`）からも利用できる。ローカル1台で使う場合は両プロセスを
ループバックで起動すればよく、計算機を別に立てる場合は UI から `WB_SERVICE_URL` でそちらを指す。構成の差は
環境変数だけで、コードは変わらない。

---

## 必要要件

| 項目 | バージョン |
|---|---|
| Python | 3.10 以上 |
| ForRocket バイナリ | v4.4.0 以上 |

### 依存パッケージ

```bash
pipenv install --dev
```

pipenv を使わない場合は `nicegui` / `fastapi` / `uvicorn` / `sqlalchemy` / `requests` / `numpy` / `scipy` /
`pandas` / `matplotlib` / `simplekml` / `tqdm` / `psutil` を入れる。

---

## セットアップ

1. リポジトリをクローンまたは展開する
2. ForRocket バイナリをリポジトリルート（または `~/ForRocket/build/`）に配置する

```
ForRocketWorkbench/
└── ForRocket        ← ここに配置（Windows なら ForRocket.exe）
```

3. 計算サービスを起動する

```bash
WB_API_TOKEN=<任意の秘密文字列> python -m service.serve
```

4. Web UI を起動する

```bash
WB_UI_PASSWORD=<ログインパスワード> WB_API_TOKEN=<上と同じ> python app_server.py
```

ブラウザで `http://127.0.0.1:8081` を開く。

### 環境変数

| 変数 | 既定 | 用途 |
|---|---|---|
| `WB_API_TOKEN` | （なし） | API のベアラトークン。**未設定では計算サービスは起動しない** |
| `WB_BIND_HOST` | `127.0.0.1` | 計算サービスの bind アドレス |
| `WB_PORT` | `8760` | 計算サービスのポート |
| `WB_DATA_ROOT` | `service_data` | ジョブ台帳（SQLite）と実行ツリーの置き場所 |
| `WB_SERVICE_URL` | `http://127.0.0.1:8760` | UI / CLI から見た計算サービスの URL |
| `WB_UI_HOST` | `127.0.0.1` | UI の bind アドレス |
| `WB_UI_PORT` | `8081` | UI のポート |
| `WB_UI_PASSWORD` | （なし） | UI のログインパスワード。**未設定では UI は起動しない** |
| `WB_UI_STORAGE_SECRET` | `WB_UI_PASSWORD` | セッション Cookie の署名鍵 |
| `WB_RESULT_ROOTS` | （なし） | `name=path,name2=path2`。外部の解析成果物を閲覧・取り込みするルート |
| `WB_VIEWER_DIST` | （なし） | 3D ビューアの静的バンドルのパス。設定すると same-origin で配信する |
| `WB_EXTERNAL_3D_URL` | （なし） | 外部 3D ビューアの URL（`WB_VIEWER_DIST` 未設定時のフォールバック） |

bind アドレスはループバックか tailscale インターフェースのみ許可される。`0.0.0.0` や LAN アドレスは
起動時に拒否される（計算サービス・UI とも）。

---

## 画面構成

### Projects (`/projects`)

サーバ側に置かれたプロジェクト（設定一式）の一覧。作成・複製・ZIP アップロード/ダウンロード・削除と、
設定の編集・計算の投入を行う。

編集画面は各設定ファイルについて **Form タブ**（型付きフォーム）と **JSON タブ**の2つを持ち、
**開いたままのタブが保存対象**になる。保存は全ファイルまとめて1回の PUT で行い、他所で更新されていた場合は
競合として検出される。

### Jobs (`/jobs`)

ジョブのキュー。検索（model / project / memo）・モード/状態フィルタ・並び替え、モンテカルロの進捗（完了数・
残り時間の見積り）、キャンセル、削除、**同一設定での再走**（後述）を行う。ワーカの生死・実行中ジョブ・
ディスク残量も表示される。

### Job detail (`/jobs/<id>`)

1ジョブの詳細と結果表示。モードによって内容が変わる。

| モード | 表示内容 |
|---|---|
| Trajectory | 飛翔サマリ（Launcher Clear / Max Q / Max Speed / Apogee / Impact）・時系列グラフ（高度・速度・マッハ・動圧・G-Load・AoA・ダウンレンジ・弾道）・落下点マップ |
| Area | 落下エリア KML ダウンロード |
| MonteCarlo | 統計サマリ（mean / σ / ±3σ）・ヒストグラム・NE 散布図（1σ/2σ/3σ 楕円）・落下点マップ（分散楕円付き） |
| Sensitivity | トルネードチャート・感度テーブル・線形性チェック散布図 |

結果は計算サービスの API 越しに読むので、UI と計算機が別ホストでも同じ画面が出る。

### Results (`/results`)

`WB_RESULT_ROOTS` で設定したディレクトリ配下の解析成果物を一覧し、3D ビューアで開く。単一飛行経路の結果は
**完了ジョブとして取り込む**こともできる（元ディレクトリはコピー元として変更されない）。

### Tools

- **Barrowman CP 計算器** (`/tools/barrowman`) — ノーズ・ボディ・フィンのジオメトリから CP 位置を計算
- **Mass & Inertia 計算器** (`/tools/mass`) — コンポーネントごとの質量・CG・慣性モーメントから合計 CG・Iyy・Ixx を計算
- **Hybrid Engine 計算器** (`/tools/engine`) — ハイブリッドエンジンの推力・比推力・酸化剤流量を計算

---

## 同一設定での再走

完了したジョブは、**まったく同じ入力**でもう一度走らせられる（Jobs 一覧と詳細の ↻ ボタン、または
`wb rerun <id>`）。ソルバや Workbench を修正したあとに、同じケースで前後比較するための機能。

- 入力は元ジョブの**実行ディレクトリからコピー**する。投入時に確定した入力そのものなので、元になった
  プロジェクトをその後編集していても再現性は損なわれない
- **新しいジョブとして**キューに入る。元ジョブは比較のために残る
- 入力の内容ハッシュを記録しており、詳細画面で元ジョブとの一致を確認できる
- 元ジョブが実行中/待機中の場合、入力がディスク上に無い場合、取り込みジョブ（結果のコピーだけを持ち、
  それを生んだ入力を持たない）の場合は再走できない

> **モンテカルロの注意**: 誤差パラメータは再サンプルされるため、同じ設定でも**母集団が変わる**。
> 比較できるのは統計量であって、ケース単位の差分ではない。他の3モードは入力が同じなら決定論的。

---

## バージョン情報

バージョンの正本は `version.py`（`__version__`）。実行時は git の情報を足した
`2.1.0+111.gb246ef1` 形式の文字列を使う（`.dirty` が付く場合は未コミットの変更がある）。

```bash
python -m cli.wb --version
python runner.py -v
python post.py -v
curl http://127.0.0.1:8760/health     # workbench_version を含む。認証不要
```

各ジョブには投入時の Workbench バージョンと、実行に使われた ForRocket バイナリのバージョンが記録され、
ジョブ詳細に表示される。UI と計算サービスのバージョンが食い違っている場合（片方だけ再起動された場合など）は
ヘッダーに警告が出る。

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
| `Time Step [s]` | 適応ステップ積分の最大刻み（上限） |
| `Solver Tolerance Abs` | 適応ステップ積分の絶対許容誤差（任意・v4.4.0+）。姿勢など小振幅状態の精度を支配。Workbench 既定 `1.0e-8`（ソルバ内部既定は `1.0e-6`） |
| `Solver Tolerance Rel` | 適応ステップ積分の相対許容誤差（任意・v4.4.0+）。ECI 位置精度と計算速度を支配。Workbench 既定 `1.0e-6` |
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

ケース数 = 風速ステップ数 × 風向ステップ数。設定エディタのフォームでリアルタイム表示される。

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

ジョブ詳細の結果表示には以下が含まれる：
- **トルネードチャート** — 各パラメータの頂点高度影響度を降順表示
- **感度テーブル** — 感度係数 [m/unit] と [m/%]、各高度値
- **線形性チェック（折りたたみ）** — 全解析点の散布図と線形傾きの比較。Reference Variations（オレンジ◆）、通常点（青●）、ノミナル（緑▲）で色分け。X・Y 軸はノミナル値を中心に対称表示。

---

## プロジェクト構成

```
ForRocketWorkbench/
├── version.py                  # バージョンの正本
├── app_server.py               # Web UI（NiceGUI）のエントリポイント
├── runner.py                   # 計算実行ラッパー（CLI）
├── post.py                     # 後処理ラッパー（CLI）
├── service/                    # 計算サービス
│   ├── serve.py                # エントリポイント・bind 制限・多重起動ロック
│   ├── api.py                  # HTTP API（FastAPI）
│   ├── worker.py               # 単一 FIFO ワーカ。runner/post を子プロセスで実行
│   ├── store.py                # ジョブ台帳（SQLite）
│   ├── rerun.py                # 同一入力での再走
│   ├── imports.py              # 外部の結果ディレクトリの取り込み
│   ├── projects.py             # サーバ側プロジェクトの CRUD
│   ├── uploads.py              # 入力クロージャの生成・検証付き展開・内容ハッシュ
│   ├── results.py / plots.py   # 結果の読み出しと作図（API 用）
│   └── client.py               # HTTP クライアント（UI・CLI が共用）
├── cli/wb.py                   # CLI クライアント
├── web/
│   ├── service_ui/             # サービス UI のページ群
│   │   ├── pages.py            # /jobs, /jobs/<id>, /results, 3D ビューア
│   │   ├── projects_ui.py      # /projects と設定エディタ
│   │   ├── config_forms.py     # 設定ファイルごとの型付きフォーム
│   │   ├── render.py           # 結果の描画
│   │   └── layout.py / theme.py / auth.py / config.py
│   ├── pages/                  # 計算に依存しないツール類
│   │   └── tools_barrowman.py / tools_mass.py / tools_engine.py
│   └── tools/                  # ツールの計算ロジック
├── runner_tool/                # 各モードのランナー
├── post_tool/                  # 各モードの後処理
├── projects/                   # プロジェクトディレクトリ
│   └── example/                # サンプル（テストが依存する）
└── tests/                      # pytest テストスイート
```

プロジェクト1つは以下の設定ファイルからなる。

```
projects/<project_name>/
├── config_solver.json
├── param_list_stage1.json
├── param_rocket.json
├── param_engine.json
├── sequence_of_event.json
├── config_area.json          # Area モード
├── config_montecarlo.json    # MonteCarlo モード
└── config_sensitivity.json   # Sensitivity モード
```

---

## テスト

```bash
pipenv run pytest tests/
```

ForRocket バイナリを必要とするテストは、バイナリが無ければ自動的にスキップされる。それ以外は外部リソース
不要で走る。テストはバージョン管理下のサンプルプロジェクト `projects/example` のみに依存する。

---

## CLI から使う場合

### 計算サービス経由（`wb`）

```bash
export WB_SERVICE_URL=http://127.0.0.1:8760
export WB_API_TOKEN=<トークン>

python -m cli.wb submit <project_dir> <mode> [--model M] [--max-thread]
python -m cli.wb list [--status STATUS]
python -m cli.wb status <job_id>
python -m cli.wb rerun <job_id> [--memo M]      # 同じ入力で再走
python -m cli.wb cancel <job_id>
python -m cli.wb pull <job_id> <dest> [--full]  # 結果を取得（--full で全ケースログ込み）
```

### ランナーを直接叩く場合

サービスを介さず単体で回す場合は以下の通り。

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

`-X` を付けると論理コア数（SMT 込み）で並列化する（Area / MonteCarlo / Sensitivity）。既定は物理コア数で、
ソルバがメモリ帯域バウンドのため通常はこちらの方が速い。

中断されたモンテカルロは、実行ディレクトリを指定して再開できる。

```bash
python ../../runner.py -s config_solver.json -m config_montecarlo.json -r work_montecarlo/<work_dir>
```
