# ForRocketWorkbench テストツール

ForRocket バイナリの実行・ランナーパイプライン・後処理を検証するテストスイートです。
バイナリが無くても動く（自己完結性・コピー・統計再構成などの）テストと、バイナリが必要な
End-to-End テストが混在します。バイナリが見つからない場合、バイナリ依存テストは自動的に
skip されます。

## 構成

```
tests/
├── conftest.py               # pytest フィクスチャ・オプション定義
├── sim_runner.py             # シミュレーション実行・メトリクス抽出コア
├── _selfcontained.py         # 自己完結性ガード（全モード共通・json_apiのキー定義を参照）
├── _project.py               # example プロジェクトのコピー／file-mode有効化ヘルパ
├── test_regression.py        # 回帰テスト（同じ入力 → 同じ出力）
├── test_behavior.py          # 挙動テスト（パラメータ変化 → 期待方向の出力変化）
├── test_copy_config_files.py # json_api.copy_config_files の単体テスト
├── test_runner_pipeline.py   # montecarlo / area パイプラインのスモークテスト
├── test_sensitivity.py       # 感度解析（計算math・出力構造・E2E）
├── test_self_contained.py    # 4モード横断の自己完結性ガード
├── test_iip.py               # IIP 後処理
├── test_import.py            # 履歴DBへの取り込み
├── test_dashboard.py         # ダッシュボード表示ロジック
└── golden/                   # 回帰テスト用ゴールデンファイル（JSON）
    └── example.json
```

## 前提

- テストは追跡対象のサンプルプロジェクト `projects/example` のみに依存します
  （実機プロジェクトは gitignore 済みのローカル専用データで、テストはこれらに依存せず、
  この public リポジトリにも一切含めません）。
- ForRocket バイナリが以下のいずれかに存在すること（優先順）
  1. `~/ForRocket/build/ForRocket`
  2. リポジトリルート `ForRocket`
  3. リポジトリルート `ForRocket.exe`

バイナリのパスを明示する場合は `--binary` オプションを使用してください。バイナリが無い
環境では、バイナリ非依存のテスト（自己完結性ガード・copy・統計再構成など）のみが実行されます。

---

## 基本的な使い方

### 全テスト実行

```bash
pytest tests/ -v
```

### 回帰テストのみ

```bash
pytest tests/test_regression.py -v
```

### 挙動テストのみ

```bash
pytest tests/test_behavior.py -v
```

### 自己完結性ガードのみ

```bash
pytest tests/test_self_contained.py -v
```

---

## 回帰テスト（test_regression.py）

「同じ入力を渡したとき、出力が前回と一致するか」を検証します。  
コードに意図しない変更が混入していないかを確認するために使います。

### ゴールデンファイルの生成（初回 or 意図的な出力変更後）

```bash
pytest tests/test_regression.py --update-golden
```

`tests/golden/example.json` が生成（上書き）されます。

### 比較実行

```bash
pytest tests/test_regression.py -v
```

各メトリクスがゴールデン値と許容誤差内に収まっているかを確認します。

### 許容誤差（TOLERANCES）

| メトリクス | 許容誤差 |
|---|---|
| apogee_altitude_m | 1.0 m |
| apogee_time_s | 0.1 s |
| apogee_downrange_m | 10.0 m |
| max_dynamic_pressure_kPa | 0.01 kPa |
| max_mach | 0.001 |
| max_acc_body_G | 0.01 G |
| landing_downrange_m | 10.0 m |
| landing_lat_deg | 1e-5 deg |
| landing_lon_deg | 1e-5 deg |
| flight_duration_s | 0.1 s |

---

## 挙動テスト（test_behavior.py）

「パラメータを変化させたとき、出力が期待した方向に変化するか」を検証します。  
物理的に正しい挙動をしているかどうかの確認に使います。

### 実装済みテスト一覧

| テスト名 | 変更内容 | 期待する変化 |
|---|---|---|
| `test_higher_elevation_raises_apogee` | 仰角 80° vs 70°（垂直に近い基準値での頭打ちを避けるため低仰角同士で比較） | 高仰角 → 最高高度が増加 |
| `test_lower_elevation_increases_downrange` | 打ち上げ仰角 -5° | 着地点水平距離が増加 |
| `test_lighter_inert_mass_raises_apogee` | 構造重量 ×0.90 | 最高高度が増加 |
| `test_higher_CA_reduces_max_mach` | 軸力係数 CA 高/低比較 | 低CA → 高Mach数 |
| `test_higher_thrust_raises_ascent_max_dynamic_pressure` | 真空中推力 高/低比較 | 高推力 → 上昇中の最大動圧が増加 |

---

## 自己完結性ガード（test_self_contained.py / _selfcontained.py）

`work_****` ディレクトリは `projects/**` 無しで再現可能でなければなりません（全入力を
work dir 配下へコピーし、相対パスで参照する）。trajectory / area / montecarlo / sensitivity
の4モードすべてで、生成された各ケースのコンフィグが「work dir 内に存在するファイルだけを
相対パスで参照している」ことを検証します。

`_selfcontained.py` のウォーカは `runner_tool.json_api` のファイル入力キー定義
（`ROCKET_FILE_INPUT_SPECS` / `ENGINE_FILE_INPUT_SPECS`）を import しているため、
プロダクト側とテスト側でキー名がドリフトしません。`_project.py` の `enable_all_file_inputs`
で全 file-mode 係数を有効化してから検証するため、「file mode × 非変動入力」経路も被覆します。

---

## オプション一覧

| オプション | 説明 |
|---|---|
| `--binary=<path>` | ForRocket バイナリのパスを明示指定 |
| `--update-golden` | ゴールデンファイルを再生成して回帰テストをスキップ |
| `-v` | 詳細出力 |
| `-k <pattern>` | テスト名でフィルタ |

### 使用例

```bash
# バイナリを明示指定して全テスト実行
pytest tests/ -v --binary=/path/to/ForRocket

# 特定のテストだけ実行
pytest tests/ -v -k "elevation"

# 回帰テストのゴールデンを更新してから全テスト実行
pytest tests/test_regression.py --update-golden
pytest tests/ -v
```

---

## 破壊的変更を加えるときのワークフロー

1. 変更前に `pytest tests/ -v` を実行してグリーンであることを確認
2. コードを変更する
3. `pytest tests/ -v` を再実行
   - 挙動テストが通る → 物理的に正しい変化
   - 回帰テストが落ちる → 出力が変わっている（意図的ならゴールデンを更新）
4. 意図的な出力変更の場合: `pytest tests/test_regression.py --update-golden` でゴールデン更新

---

## 新しいテストケースの追加

### 回帰テスト（新しい機体コンフィグ）

`test_regression.py` の `CASES` リストに追加します：

```python
CASES = [
    ("example", "example"),
    ("my_rocket", "MY_ROCKET"),  # projects/MY_ROCKET/ を追加した場合
]
```

その後 `--update-golden` でゴールデンを生成してください。なお追跡対象に含めたい場合は、
そのプロジェクトが gitignore されていないことを確認してください（現状 `projects/example`
のみが追跡対象です）。

### 挙動テスト

`test_behavior.py` に関数を追加します。`modify_configs` コールバックで任意のコンフィグキーを
変更できます：

```python
def test_my_behavior(binary_path, config_dir, example_base):
    def mod(cfgs):
        cfgs["rocket1"]["Some Key"] = new_value

    result = extract_metrics(run_sim(config_dir, _BASE_SOLVER, binary_path, modify_configs=mod))
    assert result["some_metric"] > example_base["some_metric"]
```

`cfgs` のキー構成：`"solver"`, `"stage1"`, `"rocket1"`, `"engine1"`, `"soe1"`（多段ロケットは `stage2`, `rocket2`, ... と続く）
```
